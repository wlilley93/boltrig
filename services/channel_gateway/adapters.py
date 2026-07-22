"""Platform adapter registry + the reference adapter (decision 0003, Phase 2).

The registry is the port target for real platform adapters (Slack Socket Mode,
Discord WS, Telegram long-poll, ... - see ADDING_A_PLATFORM.md). An adapter
owns exactly one thing: the PLATFORM connection. It never sees policy, grants,
or a kernel credential; inbound platform messages go to the daemon's
``on_message`` callback (which signs and POSTs the kernel intake), outbound
deliveries arrive via ``deliver`` from the kernel outbox pump.

The REFERENCE adapter here is the "custom interface": newline-delimited JSON
over a localhost TCP listener. It proves both kernel links end-to-end and
doubles as the integration contract for platform ports:

  inbound:  a peer writes ``{"id": "m1", "sender": "U-1", "text": "hi"}`` (one
            JSON object per line); the adapter hands the decoded dict to
            ``on_message``.
  outbound: ``deliver(payload)`` writes ``{"type": "outbound", ...payload}`` to
            every connected peer.

SEVERED: no ``boltrig.*`` imports (SEC-28).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

log = logging.getLogger("channel_gateway.adapters")

OnMessage = Callable[[dict[str, Any]], Awaitable[None]]


class AdapterDeliveryError(Exception):
    """A deliver() failed; the daemon fails the outbox row for retry/backoff."""


class PlatformAdapter:
    """The platform-adapter contract (interface; subclasses implement)."""

    platform = ""

    async def start(self, on_message: OnMessage) -> None:
        """Open the platform connection; call ``on_message`` per inbound event."""
        raise NotImplementedError

    async def stop(self) -> None:
        """Close the platform connection and release peers."""
        raise NotImplementedError

    async def deliver(self, payload: dict[str, Any]) -> None:
        """Deliver one outbound payload to the platform. Raise
        AdapterDeliveryError on failure (the daemon retries with backoff)."""
        raise NotImplementedError


_REGISTRY: dict[str, type[PlatformAdapter]] = {}


def register_adapter(cls: type[PlatformAdapter]) -> type[PlatformAdapter]:
    """Register an adapter class under its ``platform`` name (data, not code:
    adding a platform changes NO daemon logic)."""
    if not cls.platform:
        raise ValueError("an adapter class must name its platform")
    _REGISTRY[cls.platform] = cls
    return cls


def create_adapter(platform: str, config: dict[str, Any]) -> PlatformAdapter:
    cls = _REGISTRY.get(platform)
    if cls is None:
        raise ValueError(f"no adapter registered for platform '{platform}'")
    return cls(config)


@register_adapter
class GenericJsonLinesAdapter(PlatformAdapter):
    """The reference "custom interface" adapter (see the module docstring).

    Config: ``{"listen_host": "127.0.0.1", "listen_port": 9090}``. Port 0 asks
    for an ephemeral port (tests); the bound port is then on ``bound_port``.
    """

    platform = "generic"

    def __init__(self, config: dict[str, Any]) -> None:
        self._host = str(config.get("listen_host") or "127.0.0.1")
        self._port = int(config.get("listen_port") or 0)
        self.bound_port: int | None = None
        self._server: asyncio.AbstractServer | None = None
        self._peers: set[asyncio.StreamWriter] = set()
        self._on_message: OnMessage | None = None

    async def start(self, on_message: OnMessage) -> None:
        self._on_message = on_message
        self._server = await asyncio.start_server(self._handle_peer, self._host, self._port)
        sock = self._server.sockets[0] if self._server.sockets else None
        self.bound_port = int(sock.getsockname()[1]) if sock else None
        log.info("generic adapter listening on %s:%s", self._host, self.bound_port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        for writer in list(self._peers):
            writer.close()
        self._peers.clear()

    async def deliver(self, payload: dict[str, Any]) -> None:
        if not self._peers:
            raise AdapterDeliveryError("no connected peer to deliver to")
        line = (json.dumps({"type": "outbound", **payload}, separators=(",", ":")) + "\n").encode()
        dead = []
        for writer in list(self._peers):
            try:
                writer.write(line)
                await writer.drain()
            except (ConnectionError, RuntimeError):
                dead.append(writer)
        for writer in dead:
            self._peers.discard(writer)
        if dead and not self._peers:
            raise AdapterDeliveryError("every peer dropped mid-delivery")

    async def _handle_peer(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._peers.add(writer)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    message = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    continue  # a malformed line is dropped, never fatal
                if (
                    isinstance(message, dict)
                    and message.get("sender")
                    and message.get("text") is not None
                    and self._on_message is not None
                ):
                    await self._on_message(message)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self._peers.discard(writer)
            try:
                writer.close()
            except (ConnectionError, RuntimeError):
                pass
