"""Discord gateway (websocket) adapter for the channel gateway (decision 0003;
a platform port per ADDING_A_PLATFORM.md, modelled on the Slack reference).

Provenance (license obligation): the gateway lifecycle here - HELLO ->
IDENTIFY, the heartbeat loop with sequence tracking and zombie detection,
READY capturing ``session_id``/``resume_gateway_url``, and RESUME on reconnect
- is DERIVED from the lifecycle the MIT-licensed Hermes gateway demonstrates
(``gateway/platforms/discord.py``, Copyright (c) 2025 Nous Research, MIT
license, https://github.com/NousResearch/hermes-agent). No Hermes code is
copied (Hermes drives the discord.py SDK); the port is reimplemented against
raw httpx + websockets so the only messaging SDKs in this image are those two
pins (condition 9).

The verification boundary (condition 4, an honest statement, the SAME call the
Slack reference makes): this port is GATEWAY-ONLY - it opens NO HTTP
interactions endpoint, so there is no request-signing surface for Discord's
Ed25519 interactions-signature scheme to apply to (Ed25519 verifies the
interactions-endpoint boundary, which we do not expose; no pynacl needed).
Inbound dispatches arrive over an authenticated WSS whose URL is minted by
``GET /gateway/bot`` under the bot token: the WSS plus that token IS the
platform-side verification boundary. The kernel's canonical-HMAC intake then
covers the gateway->kernel hop exactly like the webhook class.

Egress (condition 2): the adapter dials exactly TWO endpoint families, both
checked with ``egress.egress_refusal`` before ANY dial - allow ``discord.com``
and ``discord.gg`` (suffix match covers ``gateway.discord.gg`` and the
regional resume hosts Discord hands out, e.g. ``gateway-us-east1-b.discord.gg``)
in ``CHANNEL_GATEWAY_EGRESS_ALLOW``:

  - ``https://discord.com/api/v10/gateway/bot`` (and ``/channels/{id}/messages``)
  - the ``wss://gateway*.discord.gg`` gateway / resume URLs the first call returns

Secrets (condition 7): ``bot_token`` arrives via ``config`` at spawn and is
NEVER logged - not in exceptions, not in debug lines; log messages name the
token TYPE only.
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

log = logging.getLogger("channel_gateway.discord")

_EGRESS_ALLOW_ENV = "CHANNEL_GATEWAY_EGRESS_ALLOW"
_DEFAULT_API_BASE = "https://discord.com/api/v10"
_GATEWAY_PARAMS = "?v=10&encoding=json"

# Gateway intents: GUILD_MESSAGES | DIRECT_MESSAGES | MESSAGE_CONTENT (the
# privileged content intent is required to read message text at all).
_INTENTS = (1 << 9) | (1 << 12) | (1 << 15)

# Gateway opcodes (the subset this port speaks).
_OP_DISPATCH = 0
_OP_HEARTBEAT = 1
_OP_IDENTIFY = 2
_OP_RESUME = 6
_OP_RECONNECT = 7
_OP_INVALID_SESSION = 9
_OP_HELLO = 10
_OP_HEARTBEAT_ACK = 11

_RECONNECT_SECONDS = 1.0
_RECONNECT_MAX_SECONDS = 30.0


def _env_egress_allow() -> set[str]:
    raw = os.environ.get(_EGRESS_ALLOW_ENV, "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


@register_adapter
class DiscordGatewayAdapter(PlatformAdapter):
    """Discord WS gateway port of the PlatformAdapter contract.

    Config (all injected at spawn; the token is a secret, NEVER logged):
      ``bot_token``    the bot token for IDENTIFY + the REST send
      ``api_base``     Discord REST base (default https://discord.com/api/v10;
                       a test may point it at a fake)
      ``gateway_url``  skip ``GET /gateway/bot`` and dial this WSS directly
                       (tests; production leaves it unset)
      ``egress_allow`` host set for the egress guard (default: the
                       CHANNEL_GATEWAY_EGRESS_ALLOW env at spawn)

    Inbound normalisation (the contract): a ``MESSAGE_CREATE`` dispatch becomes
    ``{"id": <message id>, "sender": <author.id>, "text": <content>,
    "thread": <channel_id>}``. The Discord message id is the platform's stable
    delivery id - it feeds the kernel's durable replay dedup. Bot/self-authored
    messages and empty-content messages (attachment-only, embeds) are ignored
    and logged at debug. ``thread`` is the channel id: the kernel stamps it on
    the reply route and the notify seam uses it verbatim as the deliver target,
    so a reply returns to the originating channel (forum-thread replies ride
    the thread's own channel id, which IS how Discord threads address).
    """

    platform = "discord"

    def __init__(self, config: dict[str, Any]) -> None:
        self._bot_token = str(config.get("bot_token") or "")
        if not self._bot_token:
            raise ValueError("discord adapter config needs bot_token")
        self._api_base = str(config.get("api_base") or _DEFAULT_API_BASE).rstrip("/")
        self._gateway_url = str(config.get("gateway_url") or "") or None
        allow = config.get("egress_allow")
        self._egress_allow = (
            {str(h).strip().lower() for h in allow if str(h).strip()}
            if allow is not None
            else _env_egress_allow()
        )
        self._http: httpx.AsyncClient | None = config.get("http_client")
        self._owns_http = self._http is None
        self._on_message: OnMessage | None = None
        self._ws: Any = None
        self._loop_task: asyncio.Task | None = None
        self._hb_task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._hb_acked = asyncio.Event()
        # the resume state, owned by the adapter (the lifecycle is WHY this
        # class of channel has a gateway at all)
        self._seq: int | None = None
        self._session_id: str | None = None
        self._resume_url: str | None = None

    # --- lifecycle ---------------------------------------------------------
    async def start(self, on_message: OnMessage) -> None:
        """Resolve the gateway URL and open the WSS; return once the socket is
        UP. Handshake/heartbeats/reconnects then run in adapter-owned tasks."""
        self._on_message = on_message
        self._stopping.clear()
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=15.0)
        await self._connect_once()  # raises: the daemon retries with backoff
        self._loop_task = asyncio.create_task(self._supervise_loop())

    async def stop(self) -> None:
        """Idempotent: safe to call twice, never hangs shutdown."""
        self._stopping.set()
        for task in (self._loop_task, self._hb_task):
            if task is not None:
                task.cancel()
        for task in (self._loop_task, self._hb_task):
            if task is not None:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        self._loop_task = self._hb_task = None
        await self._close_ws()
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    # --- the connection ----------------------------------------------------
    async def _gateway_url_now(self) -> str:
        """The WSS to dial: the resume URL while a session lives, else the
        configured override, else ``GET /gateway/bot``. Egress-checked before
        ANY dial (condition 2); the token never appears in logs or errors."""
        if self._session_id and self._resume_url:
            return self._resume_url
        if self._gateway_url:
            return self._gateway_url
        url = f"{self._api_base}/gateway/bot"
        refusal = egress_refusal(url, self._egress_allow)
        if refusal:
            raise RuntimeError(f"discord api egress-refused: {refusal}")
        try:
            resp = await self._http.get(
                url, headers={"Authorization": f"Bot {self._bot_token}"}
            )
            data = resp.json()
        except Exception as exc:
            raise RuntimeError(f"gateway/bot failed: {type(exc).__name__}") from exc
        if resp.status_code != 200 or not data.get("url"):
            raise RuntimeError(f"gateway/bot refused: {resp.status_code}")
        return str(data["url"])

    async def _connect_once(self) -> None:
        wss_url = await self._gateway_url_now()
        joiner = "&" if "?" in wss_url else "?"
        wss_url = f"{wss_url}{joiner}{_GATEWAY_PARAMS.lstrip('?')}"
        refusal = egress_refusal(wss_url, self._egress_allow)
        if refusal:
            raise RuntimeError(f"discord gateway egress-refused: {refusal}")
        try:
            self._ws = await websockets.connect(wss_url, ping_interval=20, ping_timeout=20)
        except Exception as exc:
            raise RuntimeError(f"gateway connect failed: {type(exc).__name__}") from exc
        log.info("discord gateway connected (%s)", "resume" if self._session_id else "fresh")

    async def _supervise_loop(self) -> None:
        """The adapter-owned receive/reconnect loop: run the receive loop until
        the socket drops, then re-open with backoff (resuming when a session
        survives) until stop() is called."""
        backoff = _RECONNECT_SECONDS
        while not self._stopping.is_set():
            try:
                await self._receive_loop()
                backoff = _RECONNECT_SECONDS
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - any drop reconnects
                log.warning("discord gateway dropped (%s); reconnecting", type(exc).__name__)
            await self._stop_heartbeat()
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
                log.warning("discord reconnect failed (%s)", type(exc).__name__)

    async def _receive_loop(self) -> None:
        """Read gateway payloads until the socket closes. Tracks the sequence
        number, answers server heartbeat requests, and honours RECONNECT /
        INVALID_SESSION."""
        async for raw in self._ws:
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                continue  # a malformed frame is dropped, never fatal
            if not isinstance(payload, dict):
                continue
            seq = payload.get("s")
            if isinstance(seq, int):
                self._seq = seq
            op = payload.get("op")
            if op == _OP_DISPATCH:
                await self._handle_dispatch(payload)
            elif op == _OP_HEARTBEAT:
                await self._send_heartbeat()
            elif op == _OP_RECONNECT:
                log.info("discord asked us to reconnect")
                return
            elif op == _OP_INVALID_SESSION:
                # d=True: resumable; d=False: the session is dead - drop the
                # resume state so the next connect re-identifies fresh.
                if not payload.get("d"):
                    self._session_id = None
                    self._resume_url = None
                return
            elif op == _OP_HELLO:
                interval = float((payload.get("d") or {}).get("heartbeat_interval") or 45000) / 1000.0
                await self._start_heartbeat(interval)
                await self._handshake()
            elif op == _OP_HEARTBEAT_ACK:
                self._hb_acked.set()

    async def _handshake(self) -> None:
        """RESUME when a session survives a reconnect, else IDENTIFY (with the
        intents this port needs). The token only ever rides the payload."""
        if self._session_id and self._seq is not None:
            await self._ws.send(json.dumps({
                "op": _OP_RESUME,
                "d": {"token": self._bot_token,
                      "session_id": self._session_id, "seq": self._seq},
            }))
            log.info("discord resume sent (session retained)")
            return
        await self._ws.send(json.dumps({
            "op": _OP_IDENTIFY,
            "d": {
                "token": self._bot_token,
                "intents": _INTENTS,
                "properties": {"os": "linux", "browser": "boltrig-channel-gateway",
                               "device": "boltrig-channel-gateway"},
            },
        }))

    async def _handle_dispatch(self, payload: dict[str, Any]) -> None:
        dtype = payload.get("t")
        data = payload.get("d") or {}
        if dtype == "READY":
            self._session_id = str(data.get("session_id") or "") or None
            self._resume_url = str(data.get("resume_gateway_url") or "") or None
            log.info("discord session READY")
            return
        if dtype == "RESUMED":
            log.info("discord session resumed")
            return
        if dtype != "MESSAGE_CREATE":
            log.debug("ignoring discord dispatch %s", dtype)
            return
        author = data.get("author") or {}
        if author.get("bot"):
            log.debug("ignoring a bot/self discord message")
            return
        content = str(data.get("content") or "")
        if not content:
            # attachment/embed-only messages carry no text; out of scope.
            log.debug("ignoring an empty-content discord message")
            return
        if not data.get("id") or not author.get("id") or not data.get("channel_id"):
            log.warning("discord MESSAGE_CREATE missing id/author/channel; dropping")
            return
        if self._on_message is not None:
            await self._on_message({
                "id": str(data["id"]),
                "sender": str(author["id"]),
                "text": content,
                "thread": str(data["channel_id"]),
            })

    # --- heartbeats (seq-tracked, with zombie detection) ---------------------
    async def _start_heartbeat(self, interval: float) -> None:
        await self._stop_heartbeat()
        self._hb_acked.set()
        self._hb_task = asyncio.create_task(self._heartbeat_loop(interval))

    async def _stop_heartbeat(self) -> None:
        task, self._hb_task = self._hb_task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def _heartbeat_loop(self, interval: float) -> None:
        """Beat every ``interval`` seconds with the last received seq; if the
        previous beat went un-acked the connection is a zombie - close it so
        the supervisor reconnects (and resumes)."""
        while not self._stopping.is_set():
            await self._sleep(interval)
            if self._stopping.is_set():
                return
            if not self._hb_acked.is_set():
                log.warning("discord heartbeat un-acked; cycling the zombie socket")
                await self._close_ws()
                return
            self._hb_acked.clear()
            await self._send_heartbeat()

    async def _send_heartbeat(self) -> None:
        ws = self._ws
        if ws is not None:
            await ws.send(json.dumps({"op": _OP_HEARTBEAT, "d": self._seq}))

    # --- link (b): outbound ------------------------------------------------
    async def deliver(self, payload: dict[str, Any]) -> None:
        """Post one ``channel.send`` payload (``{"text", "target"}``) via
        ``POST /channels/{target}/messages`` - ``target`` is the Discord
        channel id (the shape the inbound ``thread`` value sets on the reply
        route). Raises AdapterDeliveryError on any API failure."""
        text = str(payload.get("text") or "")
        target = str(payload.get("target") or "")
        if not target or not text:
            raise AdapterDeliveryError("deliver payload needs text + target")
        url = f"{self._api_base}/channels/{target}/messages"
        refusal = egress_refusal(url, self._egress_allow)
        if refusal:
            raise AdapterDeliveryError(f"discord api egress-refused: {refusal}")
        try:
            resp = await self._http.post(
                url, json={"content": text},
                headers={"Authorization": f"Bot {self._bot_token}"},
            )
        except Exception as exc:
            raise AdapterDeliveryError(f"channel message create failed: {type(exc).__name__}") from exc
        if resp.status_code not in (200, 201):
            raise AdapterDeliveryError(f"channel message create refused: {resp.status_code}")

    # --- helpers -------------------------------------------------------------
    async def _close_ws(self) -> None:
        ws, self._ws = self._ws, None
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()

    async def _sleep(self, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)
