"""Slack Socket Mode adapter for the channel gateway (decision 0003, the
REFERENCE platform port - see ADDING_A_PLATFORM.md).

Provenance (license obligation): the connection mechanics here - Socket Mode
connect via ``apps.connections.open``, per-envelope ack by ``envelope_id``, and
the disconnect/reconnect idiom - are DERIVED from the MIT-licensed Hermes
gateway (``gateway/platforms/slack.py``, Copyright (c) 2025 Nous Research, MIT
license, https://github.com/NousResearch/hermes-agent). No Hermes code is
copied; the port is reimplemented against raw httpx + websockets so the only
messaging SDKs in this image are those two pins (condition 9).

The verification boundary (condition 4, an honest statement): this port is
Socket-Mode-ONLY - it opens NO HTTP interactions endpoint, so there is no
request-signing surface for Slack's v0 HMAC scheme to apply to. Inbound
envelopes arrive over an authenticated WSS whose URL is minted by
``apps.connections.open`` under the app-level token (xapp): the WSS plus that
token IS the platform-side verification boundary. The kernel's canonical-HMAC
intake then covers the gateway->kernel hop exactly like the webhook class.

Egress (condition 2): the adapter dials exactly TWO endpoints, both checked
with ``egress.egress_refusal`` before connecting, and both covered by adding
``slack.com`` to ``CHANNEL_GATEWAY_EGRESS_ALLOW``:

  - ``https://slack.com/api/apps.connections.open`` (and ``chat.postMessage``)
  - the ``wss://wss-*.slack.com`` Socket Mode URL the first call returns

Secrets (condition 7): ``app_token`` (xapp) and ``bot_token`` (xoxb) arrive via
``config`` at spawn and are NEVER logged - not in exceptions, not in debug
lines; log messages name token TYPES only.

Lifecycle: ``start()`` returns once the socket is UP; the receive/reconnect
loop then runs in a task the adapter owns (the daemon only supervises start
failures - heartbeats and reconnects belong INSIDE the adapter). ``stop()`` is
idempotent and never hangs shutdown.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from typing import Any

import httpx
import websockets

from adapters import AdapterDeliveryError, OnMessage, PlatformAdapter, register_adapter
from egress import egress_refusal

log = logging.getLogger("channel_gateway.slack")

_EGRESS_ALLOW_ENV = "CHANNEL_GATEWAY_EGRESS_ALLOW"
_DEFAULT_API_BASE = "https://slack.com/api"

_RECONNECT_SECONDS = 1.0
_RECONNECT_MAX_SECONDS = 30.0


def _env_egress_allow() -> set[str]:
    raw = os.environ.get(_EGRESS_ALLOW_ENV, "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


@register_adapter
class SlackSocketAdapter(PlatformAdapter):
    """Slack Socket Mode port of the PlatformAdapter contract.

    Config (all injected at spawn; tokens are secrets, NEVER logged):
      ``app_token``    the app-level token (xapp-...) for Socket Mode
      ``bot_token``    the bot token (xoxb-...) for chat.postMessage
      ``api_base``     Slack Web API base (default https://slack.com/api; a
                       test may point it at a fake)
      ``egress_allow`` host set for the egress guard (default: the
                       CHANNEL_GATEWAY_EGRESS_ALLOW env at spawn)

    Inbound normalisation (the contract): a Socket Mode ``events_api`` envelope
    carrying a plain ``message`` event becomes
    ``{"id": <payload event_id>, "sender": <user>, "text": <text>}`` plus
    a complete reply target in ``thread``: ``channel`` for a root message or
    ``channel:thread_ts`` for a threaded message. The Slack
    ``event_id`` is the platform's stable delivery id - it feeds the kernel's
    durable replay dedup. Bot/self events (``bot_id`` present) and every
    message subtype (``message_changed`` and friends) are ignored and logged at
    debug.
    """

    platform = "slack"

    def __init__(self, config: dict[str, Any]) -> None:
        self._app_token = str(config.get("app_token") or "")
        self._bot_token = str(config.get("bot_token") or "")
        if not self._app_token or not self._bot_token:
            raise ValueError("slack adapter config needs app_token + bot_token")
        self._api_base = str(config.get("api_base") or _DEFAULT_API_BASE).rstrip("/")
        allow = config.get("egress_allow")
        self._egress_allow = (
            {str(h).strip().lower() for h in allow if str(h).strip()}
            if allow is not None
            else _env_egress_allow()
        )
        self._http: httpx.AsyncClient | None = config.get("http_client")
        self._owns_http = self._http is None
        self._ws: Any = None
        self._on_message: OnMessage | None = None
        self._loop_task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    # --- lifecycle ---------------------------------------------------------
    async def start(self, on_message: OnMessage) -> None:
        """Open the Socket Mode connection; return once the socket is UP. The
        receive/reconnect loop runs in an adapter-owned task afterwards."""
        self._on_message = on_message
        self._stopping.clear()
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=15.0)
        await self._connect_once()  # raises: the daemon retries with backoff
        self._loop_task = asyncio.create_task(self._supervise_loop())

    async def stop(self) -> None:
        """Idempotent: safe to call twice, never hangs shutdown."""
        self._stopping.set()
        task, self._loop_task = self._loop_task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await self._close_ws()
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    # --- the connection ----------------------------------------------------
    async def _connect_once(self) -> None:
        """Mint a fresh Socket Mode URL and open the WSS. Egress-checked before
        ANY dial (condition 2); token values never appear in logs or errors."""
        open_url = f"{self._api_base}/apps.connections.open"
        refusal = egress_refusal(open_url, self._egress_allow)
        if refusal:
            raise RuntimeError(f"slack api egress-refused: {refusal}")
        try:
            resp = await self._http.post(
                open_url, headers={"Authorization": f"Bearer {self._app_token}"}
            )
            data = resp.json()
        except Exception as exc:
            raise RuntimeError(f"apps.connections.open failed: {type(exc).__name__}") from exc
        if resp.status_code != 200 or not data.get("ok") or not data.get("url"):
            # Slack's error string is safe to surface; the token is not in it.
            raise RuntimeError(
                f"apps.connections.open refused: {data.get('error') or resp.status_code}"
            )
        wss_url = str(data["url"])
        refusal = egress_refusal(wss_url, self._egress_allow)
        if refusal:
            raise RuntimeError(f"slack socket egress-refused: {refusal}")
        try:
            self._ws = await websockets.connect(wss_url, ping_interval=20, ping_timeout=20)
        except Exception as exc:
            raise RuntimeError(f"socket connect failed: {type(exc).__name__}") from exc
        log.info("slack socket mode connected")

    async def _supervise_loop(self) -> None:
        """The adapter-owned receive/reconnect loop: run the receive loop until
        the socket drops (or Slack asks us to reconnect), then re-open with
        backoff until stop() is called."""
        backoff = _RECONNECT_SECONDS
        while not self._stopping.is_set():
            try:
                await self._receive_loop()
                backoff = _RECONNECT_SECONDS  # a clean disconnect: reconnect now
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - any drop reconnects
                log.warning("slack socket dropped (%s); reconnecting", type(exc).__name__)
            await self._close_ws()
            if self._stopping.is_set():
                break
            await self._sleep(backoff)
            backoff = min(backoff * 2, _RECONNECT_MAX_SECONDS)
            if self._stopping.is_set():
                break
            try:
                await self._connect_once()
            except Exception as exc:  # noqa: BLE001 - keep retrying inside
                log.warning("slack reconnect failed (%s)", type(exc).__name__)

    async def _receive_loop(self) -> None:
        """Read envelopes until the socket closes; ack EVERY envelope by id
        (Slack expects the ack within seconds, before we do any work)."""
        async for raw in self._ws:
            try:
                envelope = json.loads(raw)
            except (TypeError, ValueError):
                continue  # a malformed frame is dropped, never fatal
            if not isinstance(envelope, dict):
                continue
            envelope_id = envelope.get("envelope_id")
            if envelope_id:
                await self._ws.send(json.dumps({"envelope_id": envelope_id}))
            etype = envelope.get("type")
            if etype == "disconnect":
                # Slack's polite reconnect request: return so the supervisor
                # re-opens a fresh URL (the reason is safe to log).
                log.info("slack asked us to reconnect (%s)", envelope.get("reason"))
                return
            if etype == "events_api":
                await self._handle_events_api(envelope.get("payload") or {})

    async def _handle_events_api(self, payload: dict[str, Any]) -> None:
        event = payload.get("event") or {}
        if event.get("type") != "message":
            log.debug("ignoring slack event type %s", event.get("type"))
            return
        if event.get("subtype") is not None:
            # message_changed / message_deleted / bot_message / ...: not new
            # human input (a bot-self echo arrives as subtype bot_message).
            log.debug("ignoring slack message subtype %s", event.get("subtype"))
            return
        if event.get("bot_id") or not event.get("user"):
            log.debug("ignoring a bot/self slack event")
            return
        event_id = str(payload.get("event_id") or "")
        if not event_id:
            # Without the stable event id the kernel cannot dedup replays;
            # better to drop loud than ingest twice.
            log.warning("slack events_api envelope had no event_id; dropping")
            return
        channel = str(event.get("channel") or "")
        if not channel:
            # A Slack message without its channel cannot be replied to safely.
            log.warning("slack message event had no channel; dropping")
            return
        thread_ts = str(event.get("thread_ts") or "")
        reply_target = f"{channel}:{thread_ts}" if thread_ts else channel
        message: dict[str, Any] = {
            "id": event_id,
            "sender": str(event["user"]),
            "text": str(event.get("text") or ""),
            # ``thread`` is always the COMPLETE outbound target.  Keeping only
            # thread_ts here made the notification seam parse it as a channel.
            "thread": reply_target,
            "provider_message_id": str(event.get("ts") or event_id),
            "provider_sender_id": str(event["user"]),
            "provider_conversation_id": reply_target,
            "provider_timestamp": str(event.get("ts") or ""),
            "threaded": bool(thread_ts),
        }
        if self._on_message is not None:
            await self._on_message(message)

    # --- link (b): outbound ------------------------------------------------
    async def deliver(self, payload: dict[str, Any]) -> None:
        """Post one ``channel.send`` payload (``{"text", "target"}``) via
        chat.postMessage. ``target`` is the Slack channel id, or
        ``"channel:thread_ts"`` for a thread reply (the kernel's reply_route
        thread value). Raises AdapterDeliveryError on any API failure."""
        text = str(payload.get("text") or "")
        target = str(payload.get("target") or "")
        channel, sep, thread_ts = target.partition(":")
        if not channel or not text:
            raise AdapterDeliveryError("deliver payload needs text + target")
        post_url = f"{self._api_base}/chat.postMessage"
        refusal = egress_refusal(post_url, self._egress_allow)
        if refusal:
            raise AdapterDeliveryError(f"slack api egress-refused: {refusal}")
        body: dict[str, Any] = {"channel": channel, "text": text}
        if sep and thread_ts:
            body["thread_ts"] = thread_ts
        try:
            resp = await self._http.post(
                post_url,
                json=body,
                headers={"Authorization": f"Bearer {self._bot_token}"},
            )
            data = resp.json()
        except Exception as exc:
            raise AdapterDeliveryError(f"chat.postMessage failed: {type(exc).__name__}") from exc
        if resp.status_code != 200 or not data.get("ok"):
            raise AdapterDeliveryError(
                f"chat.postMessage refused: {data.get('error') or resp.status_code}"
            )

    # --- helpers -------------------------------------------------------------
    async def _close_ws(self) -> None:
        ws, self._ws = self._ws, None
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()

    async def _sleep(self, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)
