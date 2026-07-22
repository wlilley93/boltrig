"""Signal adapter for the channel gateway (decision 0003; a platform port per
ADDING_A_PLATFORM.md, modelled on the Slack reference).

Provenance (license obligation): the integration shape here - a signal-cli
daemon (the ``bbernhard/signal-cli-rest-api`` sibling service, json-rpc mode)
with inbound envelopes arriving over its SSE stream (``GET /api/v1/events``)
and outbound sends as JSON-RPC 2.0 over HTTP (``POST /api/v1/rpc``, method
``send``) - is DERIVED from the MIT-licensed Hermes gateway
(``gateway/platforms/signal.py``, Copyright (c) 2025 Nous Research, MIT
license, https://github.com/NousResearch/hermes-agent). No Hermes code is
copied; the port is reimplemented against raw httpx (Hermes's attachment /
mention / rate-limit-scheduler surface is OUT of scope - text messages only).

The verification boundary (condition 4, an honest statement): Signal protocol
verification (sealed sender, safety numbers) terminates INSIDE the signal-cli
daemon, which holds the account keys - the gateway never sees plaintext key
material. The gateway<->signal-cli hop is operator-internal (the sibling
container on the compose sandbox network); the platform-side boundary is the
daemon's registered account itself. The kernel's canonical-HMAC intake then
covers the gateway->kernel hop exactly like the webhook class.

Egress (condition 2): the adapter dials ONE host - the signal-cli daemon -
checked with ``egress.egress_refusal`` before ANY dial. Allow the compose
service name (``signal-cli``) in ``CHANNEL_GATEWAY_EGRESS_ALLOW``:

  - ``http://signal-cli:8080/api/v1/check`` (liveness at start)
  - ``http://signal-cli:8080/api/v1/events?account=...`` (SSE inbound)
  - ``http://signal-cli:8080/api/v1/rpc`` (JSON-RPC outbound)

Secrets (condition 7): the account keys never leave the signal-cli container.
The registered ``account`` NUMBER arrives via ``config`` at spawn (the
connect-time injection); it is an identifier, not a credential, but it is
still never logged - envelopes are logged by shape only.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from typing import Any

import httpx

from adapters import AdapterDeliveryError, OnMessage, PlatformAdapter, register_adapter
from egress import egress_refusal

log = logging.getLogger("channel_gateway.signal")

_EGRESS_ALLOW_ENV = "CHANNEL_GATEWAY_EGRESS_ALLOW"
_DEFAULT_HTTP_URL = "http://127.0.0.1:8080"

_RECONNECT_SECONDS = 1.0
_RECONNECT_MAX_SECONDS = 30.0


def _env_egress_allow() -> set[str]:
    raw = os.environ.get(_EGRESS_ALLOW_ENV, "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


@register_adapter
class SignalCliAdapter(PlatformAdapter):
    """signal-cli JSON-RPC/SSE port of the PlatformAdapter contract.

    Config (all injected at spawn):
      ``http_url``     the signal-cli daemon base URL (default
                       http://127.0.0.1:8080; in compose:
                       http://signal-cli:8080)
      ``account``      the registered Signal account number (E.164) the
                       daemon serves; connect-time injected, never logged
      ``egress_allow`` host set for the egress guard (default: the
                       CHANNEL_GATEWAY_EGRESS_ALLOW env at spawn)

    Inbound normalisation (the contract): an SSE envelope whose ``dataMessage``
    carries text becomes ``{"id": <envelope timestamp>, "sender": <source
    number>, "text": <message>, "thread": <sender or "group:<group id>">}``.
    The envelope timestamp is Signal's stable delivery id - it feeds the
    kernel's durable replay dedup. ``thread`` is a COMPLETE deliver target
    (the kernel stamps it on the reply route and the notify seam uses it
    verbatim as the outbound ``target``): the sender's number for a DM,
    ``group:<id>`` for a group (V2 ``groupV2.id`` first, legacy
    ``groupInfo.groupId`` fallback, mirroring Hermes). Receipts, typing
    indicators, stories, sync traffic, self-echoes and contentless envelopes
    are ignored and logged at debug.
    """

    platform = "signal"

    def __init__(self, config: dict[str, Any]) -> None:
        self._account = str(config.get("account") or "")
        if not self._account:
            raise ValueError("signal adapter config needs account")
        self._http_url = str(config.get("http_url") or _DEFAULT_HTTP_URL).rstrip("/")
        allow = config.get("egress_allow")
        self._egress_allow = (
            {str(h).strip().lower() for h in allow if str(h).strip()}
            if allow is not None
            else _env_egress_allow()
        )
        self._http: httpx.AsyncClient | None = config.get("http_client")
        self._owns_http = self._http is None
        self._on_message: OnMessage | None = None
        self._loop_task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    # --- lifecycle ---------------------------------------------------------
    async def start(self, on_message: OnMessage) -> None:
        """Check the daemon is up, then return; the SSE listener (with
        reconnect/backoff) runs in an adapter-owned task afterwards."""
        self._on_message = on_message
        self._stopping.clear()
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=15.0)
        await self._check_daemon()  # raises: the daemon retries with backoff
        log.info("signal-cli daemon reachable; SSE listener starting")
        self._loop_task = asyncio.create_task(self._sse_loop())

    async def stop(self) -> None:
        """Idempotent: safe to call twice, never hangs shutdown."""
        self._stopping.set()
        task, self._loop_task = self._loop_task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    def _check_egress(self, url: str, what: str) -> None:
        refusal = egress_refusal(url, self._egress_allow)
        if refusal:
            raise RuntimeError(f"signal-cli {what} egress-refused: {refusal}")

    async def _check_daemon(self) -> None:
        url = f"{self._http_url}/api/v1/check"
        self._check_egress(url, "check")
        try:
            resp = await self._http.get(url)
        except Exception as exc:
            raise RuntimeError(f"signal-cli check failed: {type(exc).__name__}") from exc
        if resp.status_code >= 400:
            raise RuntimeError(f"signal-cli check refused: {resp.status_code}")

    # --- link (a): inbound (the SSE stream) ---------------------------------
    async def _sse_loop(self) -> None:
        """Stream envelopes from the daemon forever; any drop reconnects with
        backoff until stop() is called (the SSE reconnect idiom is Hermes's)."""
        backoff = _RECONNECT_SECONDS
        url = f"{self._http_url}/api/v1/events"
        while not self._stopping.is_set():
            self._check_egress(url, "events")
            try:
                async with self._http.stream(
                    "GET", url, params={"account": self._account}, timeout=None
                ) as resp:
                    if resp.status_code >= 400:
                        raise RuntimeError(f"events refused: {resp.status_code}")
                    backoff = _RECONNECT_SECONDS
                    async for line in resp.aiter_lines():
                        if self._stopping.is_set():
                            return
                        await self._handle_sse_line(line)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - any drop reconnects
                log.warning("signal SSE dropped (%s); reconnecting", type(exc).__name__)
            if self._stopping.is_set():
                break
            await self._sleep(backoff)
            backoff = min(backoff * 2, _RECONNECT_MAX_SECONDS)

    async def _handle_sse_line(self, line: str) -> None:
        if not line.startswith("data:"):
            return  # keepalive comments and event: lines carry no payload
        try:
            payload = json.loads(line[5:].strip())
        except ValueError:
            log.debug("ignoring an undecodable signal SSE line")
            return
        if isinstance(payload, dict):
            await self._handle_envelope(payload)

    async def _handle_envelope(self, payload: dict[str, Any]) -> None:
        envelope = payload.get("envelope", payload)
        if not isinstance(envelope, dict):
            return
        if envelope.get("receiptMessage") or envelope.get("typingMessage"):
            log.debug("ignoring a signal receipt/typing envelope")
            return
        if envelope.get("storyMessage"):
            log.debug("ignoring a signal story envelope")
            return
        if envelope.get("syncMessage"):
            # our own outbound traffic mirrored back; never new human input
            log.debug("ignoring a signal sync envelope")
            return
        data_message = envelope.get("dataMessage")
        if not isinstance(data_message, dict):
            log.debug("ignoring a signal envelope with no dataMessage")
            return
        sender = (
            envelope.get("sourceNumber")
            or envelope.get("sourceUuid")
            or envelope.get("source")
        )
        if not sender:
            log.debug("ignoring a signal envelope with no sender")
            return
        if sender == self._account:
            log.debug("ignoring a signal self-echo")
            return
        text = str(data_message.get("message") or "")
        if not text.strip():
            # profile-key updates and attachment-only messages carry no text
            log.debug("ignoring a contentless signal envelope")
            return
        timestamp = envelope.get("timestamp")
        if timestamp is None:
            # Without the envelope timestamp the kernel cannot dedup replays;
            # better to drop loud than ingest twice.
            log.warning("signal envelope had no timestamp; dropping")
            return
        group_v2 = data_message.get("groupV2")
        group_info = data_message.get("groupInfo")
        group_id = (
            (group_v2.get("id") if isinstance(group_v2, dict) else None)
            or (group_info.get("groupId") if isinstance(group_info, dict) else None)
        )
        thread = f"group:{group_id}" if group_id else str(sender)
        if self._on_message is not None:
            await self._on_message({
                "id": str(timestamp),
                "sender": str(sender),
                "text": text,
                "thread": thread,
            })

    # --- link (b): outbound ------------------------------------------------
    async def deliver(self, payload: dict[str, Any]) -> None:
        """Send one ``channel.send`` payload (``{"text", "target"}``) via the
        JSON-RPC ``send`` method. ``target`` is the recipient number, or
        ``"group:<group id>"`` for a group (the shape the inbound ``thread``
        value sets on the reply route). Raises AdapterDeliveryError on any
        RPC failure."""
        text = str(payload.get("text") or "")
        target = str(payload.get("target") or "")
        if not target or not text:
            raise AdapterDeliveryError("deliver payload needs text + target")
        params: dict[str, Any] = {"account": self._account, "message": text}
        if target.startswith("group:"):
            params["groupId"] = target[len("group:"):]
        else:
            params["recipient"] = [target]
        url = f"{self._http_url}/api/v1/rpc"
        self._check_egress(url, "rpc")
        request = {
            "jsonrpc": "2.0",
            "method": "send",
            "params": params,
            "id": f"send_{int(time.time() * 1000)}",
        }
        try:
            resp = await self._http.post(url, json=request)
            data = resp.json()
        except Exception as exc:
            raise AdapterDeliveryError(f"signal rpc send failed: {type(exc).__name__}") from exc
        if resp.status_code >= 400:
            raise AdapterDeliveryError(f"signal rpc send refused: {resp.status_code}")
        if data.get("error"):
            # signal-cli's error object never contains the account keys; safe
            raise AdapterDeliveryError(f"signal rpc send error: {data['error']}")

    # --- helpers -------------------------------------------------------------
    async def _sleep(self, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)
