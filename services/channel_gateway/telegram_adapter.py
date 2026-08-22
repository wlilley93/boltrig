"""Telegram Bot API long-poll adapter for the channel gateway (decision 0003;
a platform port per ADDING_A_PLATFORM.md, modelled on the Slack reference).

Provenance (license obligation): the connection mechanics here - ``getUpdates``
long-poll with a monotonically advancing ``offset`` (resume by acknowledging
every update up to the last seen ``update_id``) and ``sendMessage`` for
outbound - are DERIVED from the MIT-licensed Hermes gateway
(``gateway/platforms/telegram.py``, Copyright (c) 2025 Nous Research, MIT
license, https://github.com/NousResearch/hermes-agent). No Hermes code is
copied; the port is reimplemented against raw httpx (Hermes's media / sticker /
topic-command surface is OUT of scope - text messages only).

An HONEST shape statement: Telegram bots (without a self-hosted Bot API server
or a webhook endpoint) have NO socket - long-poll IS the platform's transport
for this class. The adapter owns the poll loop with reconnect/backoff exactly
like the socket adapters own their receive loops, so the daemon's lifecycle
contract is unchanged.

The verification boundary (condition 4, an honest statement): there is no
per-request signature scheme on the Bot API long-poll path - the bot token is
IN the URL path of every call over TLS to api.telegram.org, and the poll
response can only be read by the token holder. The token-scoped TLS channel IS
the platform-side verification boundary (same posture as Slack Socket Mode's
authenticated WSS); the kernel's canonical-HMAC intake then covers the
gateway->kernel hop.

Egress (condition 2): the adapter dials ONE host, checked with
``egress.egress_refusal`` before ANY dial - add ``api.telegram.org`` to
``CHANNEL_GATEWAY_EGRESS_ALLOW``:

  - ``https://api.telegram.org/bot<token>/getMe|getUpdates|sendMessage``

Secrets (condition 7): ``bot_token`` arrives via ``config`` at spawn and is
NEVER logged - not in exceptions, not in debug lines; log messages name the
token TYPE only (the token never appears in a URL we log either: refusals and
errors are raised with the endpoint NAME, not the URL).

Delivery-id honesty: ``update_id`` is the platform's stable delivery id - it
feeds the kernel's durable replay dedup. The offset cursor is held in memory
only: a gateway restart re-polls from Telegram's server-side queue and may
redeliver recent updates once; the kernel's dedup (keyed on update_id) is the
resume authority, as the contract intends.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from typing import Any

import httpx

from adapters import AdapterDeliveryError, OnMessage, PlatformAdapter, register_adapter
from egress import egress_refusal

log = logging.getLogger("channel_gateway.telegram")

_EGRESS_ALLOW_ENV = "CHANNEL_GATEWAY_EGRESS_ALLOW"
_DEFAULT_API_BASE = "https://api.telegram.org"

_LONG_POLL_TIMEOUT_SECONDS = 30
_RECONNECT_SECONDS = 1.0
_RECONNECT_MAX_SECONDS = 30.0


def _env_egress_allow() -> set[str]:
    raw = os.environ.get(_EGRESS_ALLOW_ENV, "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


@register_adapter
class TelegramLongPollAdapter(PlatformAdapter):
    """Telegram Bot API long-poll port of the PlatformAdapter contract.

    Config (all injected at spawn; the token is a secret, NEVER logged):
      ``bot_token``    the Bot API token (123456:ABC-...) for getUpdates +
                       sendMessage
      ``api_base``     Bot API base (default https://api.telegram.org; a test
                       may point it at a fake)
      ``egress_allow`` host set for the egress guard (default: the
                       CHANNEL_GATEWAY_EGRESS_ALLOW env at spawn)

    Inbound normalisation (the contract): a ``message`` update carrying text
    becomes ``{"id": <update_id>, "sender": <from.id>, "text": <text>,
    "thread": <chat_id or "chat_id:message_thread_id">}``. The ``thread``
    value is a COMPLETE deliver target (the kernel stamps it on the reply
    route and the notify seam uses it verbatim as the outbound ``target``):
    the bare chat id for ordinary chats, ``chat_id:message_thread_id`` for
    forum-topic messages so a reply lands back in the originating topic.
    Service updates (new_chat_members, pins, ...), media-only messages, edited
    messages and bot-authored messages are ignored and logged at debug.
    """

    platform = "telegram"

    def __init__(self, config: dict[str, Any]) -> None:
        self._bot_token = str(config.get("bot_token") or "")
        if not self._bot_token:
            raise ValueError("telegram adapter config needs bot_token")
        self._api_base = str(config.get("api_base") or _DEFAULT_API_BASE).rstrip("/")
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
        self._next_offset: int | None = None  # the long-poll resume cursor

    # --- the Bot API URL (token lives in the path; NEVER logged) ------------
    def _url(self, method: str) -> str:
        return f"{self._api_base}/bot{self._bot_token}/{method}"

    def _check_egress(self, method: str) -> None:
        """Egress-gate a Bot API call by METHOD NAME (condition 2). Refusals
        name the method, never the URL - the URL carries the token."""
        refusal = egress_refusal(self._url(method), self._egress_allow)
        if refusal:
            raise RuntimeError(f"telegram api egress-refused on {method}: {refusal}")

    async def _call(self, method: str, body: dict[str, Any], *, timeout: float = 15.0) -> dict:
        """One Bot API call; raises RuntimeError on transport/API failure with
        the token never surfaced (endpoint named by method only)."""
        self._check_egress(method)
        try:
            resp = await self._http.post(self._url(method), json=body, timeout=timeout)
            data = resp.json()
        except Exception as exc:
            raise RuntimeError(f"telegram {method} failed: {type(exc).__name__}") from exc
        if resp.status_code != 200 or not data.get("ok"):
            # Telegram's description is safe to surface; the token is not in it.
            raise RuntimeError(
                f"telegram {method} refused: {data.get('description') or resp.status_code}"
            )
        return data.get("result") or {}

    # --- lifecycle ---------------------------------------------------------
    async def start(self, on_message: OnMessage) -> None:
        """Verify the token (getMe) and return once the API is UP; the poll
        loop then runs in an adapter-owned task (the daemon only supervises
        start failures - reconnect/backoff belongs INSIDE the adapter)."""
        self._on_message = on_message
        self._stopping.clear()
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=_LONG_POLL_TIMEOUT_SECONDS + 15.0)
        me = await self._call("getMe", {})  # raises: the daemon retries
        log.info("telegram bot authenticated as @%s", me.get("username"))
        self._loop_task = asyncio.create_task(self._poll_loop())

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

    # --- link (a): inbound (the long-poll loop) -----------------------------
    async def _poll_loop(self) -> None:
        """Long-poll getUpdates forever; any drop reconnects with backoff until
        stop() is called. ``offset`` resumes past every update already seen."""
        backoff = _RECONNECT_SECONDS
        while not self._stopping.is_set():
            body: dict[str, Any] = {
                "timeout": _LONG_POLL_TIMEOUT_SECONDS,
                "allowed_updates": ["message"],
            }
            if self._next_offset is not None:
                body["offset"] = self._next_offset
            try:
                result = await self._call(
                    "getUpdates", body, timeout=_LONG_POLL_TIMEOUT_SECONDS + 15.0
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - any drop retries inside
                log.warning("telegram poll dropped (%s); reconnecting", type(exc).__name__)
                await self._sleep(backoff)
                backoff = min(backoff * 2, _RECONNECT_MAX_SECONDS)
                continue
            backoff = _RECONNECT_SECONDS
            for update in result if isinstance(result, list) else []:
                await self._handle_update(update)

    async def _handle_update(self, update: dict[str, Any]) -> None:
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            # advance the resume cursor FIRST: an acked update is never re-read
            # by this process even if normalisation drops it.
            self._next_offset = update_id + 1
        message = update.get("message")
        if not isinstance(message, dict):
            log.debug("ignoring telegram non-message update")
            return
        sender = message.get("from") or {}
        if sender.get("is_bot"):
            log.debug("ignoring a bot-authored telegram message")
            return
        text = message.get("text")
        if not text:
            # service messages (new_chat_members, pinned, ...) and media-only
            # messages carry no text; out of scope for this port.
            log.debug("ignoring a telegram message with no text")
            return
        if update_id is None or not sender.get("id"):
            # Without the stable update id the kernel cannot dedup replays;
            # better to drop loud than ingest twice.
            log.warning("telegram update had no update_id/from.id; dropping")
            return
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            log.debug("ignoring a telegram message with no chat id")
            return
        topic_id = message.get("message_thread_id")
        thread = f"{chat_id}:{topic_id}" if topic_id is not None else str(chat_id)
        if self._on_message is not None:
            await self._on_message(
                {
                    "id": str(update_id),
                    "sender": str(sender["id"]),
                    "text": str(text),
                    "thread": thread,
                    "provider_message_id": str(message.get("message_id") or update_id),
                    "provider_sender_id": str(sender["id"]),
                    "provider_conversation_id": thread,
                    "provider_timestamp": message.get("date"),
                    "threaded": topic_id is not None,
                }
            )

    # --- link (b): outbound ------------------------------------------------
    async def deliver(self, payload: dict[str, Any]) -> None:
        """Send one ``channel.send`` payload (``{"text", "target"}``) via
        sendMessage. ``target`` is the chat id, or ``"chat_id:message_thread_id"``
        for a forum-topic reply (the shape the inbound ``thread`` value sets on
        the reply route). Raises AdapterDeliveryError on any API failure."""
        text = str(payload.get("text") or "")
        target = str(payload.get("target") or "")
        chat_id, sep, topic_id = target.partition(":")
        if not chat_id or not text:
            raise AdapterDeliveryError("deliver payload needs text + target")
        body: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if sep and topic_id:
            try:
                body["message_thread_id"] = int(topic_id)
            except ValueError:
                raise AdapterDeliveryError(f"bad topic id in target: {topic_id!r}") from None
        try:
            await self._call("sendMessage", body)
        except RuntimeError as exc:
            raise AdapterDeliveryError(str(exc)) from exc

    # --- helpers -------------------------------------------------------------
    async def _sleep(self, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)
