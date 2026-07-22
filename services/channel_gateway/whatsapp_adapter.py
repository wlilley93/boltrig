"""WhatsApp adapter for the channel gateway (decision 0003; item 7 of the
platform plan) - a port of the PlatformAdapter contract that terminates at a
LOCAL Baileys bridge process instead of dialing the platform directly.

Architecture (condition 9, honestly stated): the WhatsApp messaging SDK is
Baileys, a Node.js library - it CANNOT live in this Python image, so it runs
as a sibling Node process (``whatsapp_bridge/``, derived from the
MIT-licensed Hermes bridge, Copyright (c) 2025 Nous Research - see
``whatsapp_bridge/LICENSE.md``). This adapter owns the Python side of the
loopback HTTP contract between the two:

  inbound:  the bridge normalises each accepted Baileys message and PUSHes it
            as JSON to this adapter's local listener (``POST /inbound``);
            the adapter hands ``{"id", "sender", "text", "thread"}`` to
            ``on_message``;
  outbound: ``deliver({"text", "target"})`` POSTs ``{"chatId", "message"}``
            to the bridge's ``/send`` endpoint.

The bridge<->adapter event shape (the contract):
  ``{"messageId", "chatId", "senderId", "isGroup", "body"}``

Normalisation (the adapter contract): Baileys ``messageId`` (the message
``key.id``) is the platform's stable delivery id - it feeds the kernel's
durable replay dedup. ``sender`` is the JID user part (``senderId`` up to the
``@``): the phone number for classic JIDs, the LID number for linked-identity
JIDs - either way the stable per-user identifier the kernel's binding rows
match as ``external_user_id``. ``thread`` is ALWAYS the ``chatId``: the chat
JID is the way back (channel_notify delivers replies to
``reply_route["thread"]``), so a DM replies to the phone JID and a group
message - ``isGroup`` true, sender from the participant JID - carries the
group JID as its thread and replies land back in the group. Native media,
message edit and typing indicators are follow-ons (the bridge forwards media
captions as text).

Policy (condition 2): the adapter and bridge own NO who-may-talk decision -
the Hermes allowlist/self-chat policy was stripped from the vendored bridge;
every inbound human message reaches the ONE intake and the kernel binding
decides. The bridge drops only its own fromMe echoes, status broadcasts and
empty/system messages (loop prevention, mechanics not policy).

The verification boundary (condition 4, an honest statement): WhatsApp has no
request-signing surface - Baileys terminates WhatsApp's own E2EE (Signal
protocol) inside the bridge process; the session credentials on disk under
the bridge's ``--session`` dir ARE the platform-side verification boundary,
exactly as the Slack port's WSS-plus-xapp-token is. The kernel's
canonical-HMAC intake then covers the gateway->kernel hop unchanged.

Egress (condition 2): the adapter dials exactly ONE endpoint - the bridge's
``POST /send`` - checked with ``egress.egress_refusal`` before connecting;
cover it by adding the bridge host (``127.0.0.1`` when co-located) to
``CHANNEL_GATEWAY_EGRESS_ALLOW``. The inbound listener binds loopback.

Secrets (condition 7): none. The adapter holds no token at all; the WhatsApp
session credentials live in the bridge's session dir, operator-mounted.

Lifecycle: ``start()`` returns once the local listener is UP (the bridge
connects outward to WhatsApp on its own and pushes when ready - a bridge that
is down simply means no inbound; outbound dials fail into AdapterDeliveryError
and the outbox retry/backoff). ``stop()`` is idempotent and never hangs
shutdown.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from adapters import AdapterDeliveryError, OnMessage, PlatformAdapter, register_adapter
from egress import egress_refusal

log = logging.getLogger("channel_gateway.whatsapp")

_EGRESS_ALLOW_ENV = "CHANNEL_GATEWAY_EGRESS_ALLOW"
_DEFAULT_BRIDGE_BASE = "http://127.0.0.1:3000"


def _env_egress_allow() -> set[str]:
    raw = os.environ.get(_EGRESS_ALLOW_ENV, "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


@register_adapter
class WhatsAppBridgeAdapter(PlatformAdapter):
    """WhatsApp-via-Baileys-bridge port of the PlatformAdapter contract.

    Config (all injected at spawn):
      ``bridge_base``   the bridge's base URL (default
                        http://127.0.0.1:3000; a test points it at a fake)
      ``listen_host``   bind host for the inbound listener (default
                        127.0.0.1 - the bridge is a same-host peer)
      ``listen_port``   bind port for the inbound listener; 0 asks for an
                        ephemeral port (tests), the bound port lands on
                        ``bound_port``. The operator passes this port to the
                        bridge as ``--adapter-url http://127.0.0.1:PORT/inbound``
      ``egress_allow``  host set for the egress guard (default: the
                        CHANNEL_GATEWAY_EGRESS_ALLOW env at spawn) - the
                        bridge host only
      ``http_client``   injectable httpx.AsyncClient (tests)
    """

    platform = "whatsapp"

    def __init__(self, config: dict[str, Any]) -> None:
        self._bridge_base = str(config.get("bridge_base") or _DEFAULT_BRIDGE_BASE).rstrip("/")
        self._listen_host = str(config.get("listen_host") or "127.0.0.1")
        self._listen_port = int(config.get("listen_port") or 0)
        allow = config.get("egress_allow")
        self._egress_allow = (
            {str(h).strip().lower() for h in allow if str(h).strip()}
            if allow is not None
            else _env_egress_allow()
        )
        self._http: httpx.AsyncClient | None = config.get("http_client")
        self._owns_http = self._http is None
        self._on_message: OnMessage | None = None
        self._server: uvicorn.Server | None = None
        self._server_task: asyncio.Task | None = None
        self.bound_port: int | None = None

    # --- lifecycle ---------------------------------------------------------
    async def start(self, on_message: OnMessage) -> None:
        """Bind the local inbound listener; return once it is UP. The bridge
        pushes inbound events here; there is no socket to hold open."""
        self._on_message = on_message
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=15.0)
        listener = FastAPI(title="channel-gateway whatsapp inbound")
        listener.post("/inbound")(self._handle_inbound)
        config = uvicorn.Config(
            listener, host=self._listen_host, port=self._listen_port, log_level="warning"
        )
        self._server = uvicorn.Server(config)
        self._server_task = asyncio.create_task(self._server.serve())
        for _ in range(500):  # up to ~5s for the bind
            if self._server.started:
                break
            if self._server_task.done():
                # surface the bind failure so the daemon retries with backoff
                exc = self._server_task.exception()
                raise RuntimeError(f"whatsapp listener failed to bind: {type(exc).__name__}")
            await asyncio.sleep(0.01)
        if not self._server.started:
            raise RuntimeError("whatsapp listener did not come up")
        sock = self._server.servers[0].sockets[0]
        self.bound_port = int(sock.getsockname()[1])
        log.info("whatsapp inbound listener on %s:%s", self._listen_host, self.bound_port)

    async def stop(self) -> None:
        """Idempotent: safe to call twice, never hangs shutdown."""
        server, self._server = self._server, None
        task, self._server_task = self._server_task, None
        if server is not None:
            server.should_exit = True
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    # --- link (a): inbound -------------------------------------------------
    async def _handle_inbound(self, request: Request) -> JSONResponse:
        """Receive one bridge event; normalise and hand to the daemon's
        on_message. A missing stable id is refused loud (400) - without it the
        kernel cannot dedup replays; better to drop than ingest twice."""
        try:
            event = await request.json()
        except ValueError:
            return JSONResponse({"ok": False, "error": "invalid json"}, status_code=400)
        if not isinstance(event, dict):
            return JSONResponse({"ok": False, "error": "invalid event"}, status_code=400)
        message_id = str(event.get("messageId") or "")
        sender_jid = str(event.get("senderId") or "")
        chat_id = str(event.get("chatId") or "")
        if not message_id or not sender_jid or not chat_id:
            log.warning("whatsapp bridge event missing messageId/senderId/chatId; refusing")
            return JSONResponse({"ok": False, "error": "incomplete event"}, status_code=400)
        if chat_id == "status@broadcast":
            log.debug("ignoring a whatsapp status broadcast")
            return JSONResponse({"ok": True, "ignored": True})
        message: dict[str, Any] = {
            "id": message_id,
            # the JID user part: phone number (s.whatsapp.net) or LID number
            "sender": sender_jid.split("@")[0],
            "text": str(event.get("body") or ""),
            # the chat JID is the way back (DM phone JID or group JID alike)
            "thread": chat_id,
        }
        if self._on_message is not None:
            await self._on_message(message)
        return JSONResponse({"ok": True})

    # --- link (b): outbound ------------------------------------------------
    async def deliver(self, payload: dict[str, Any]) -> None:
        """POST one ``channel.send`` payload (``{"text", "target"}``) to the
        bridge's /send; ``target`` is the chat JID (the inbound thread value).
        Raises AdapterDeliveryError on any bridge failure - the daemon fails
        the outbox row and the kernel retries with backoff."""
        text = str(payload.get("text") or "")
        target = str(payload.get("target") or "")
        if not target or not text:
            raise AdapterDeliveryError("deliver payload needs text + target")
        send_url = f"{self._bridge_base}/send"
        refusal = egress_refusal(send_url, self._egress_allow)
        if refusal:
            raise AdapterDeliveryError(f"whatsapp bridge egress-refused: {refusal}")
        try:
            resp = await self._http.post(
                send_url, json={"chatId": target, "message": text}
            )
            data = resp.json()
        except Exception as exc:
            raise AdapterDeliveryError(f"bridge send failed: {type(exc).__name__}") from exc
        if resp.status_code != 200 or not data.get("success"):
            raise AdapterDeliveryError(f"bridge send refused: {data.get('error') or resp.status_code}")
