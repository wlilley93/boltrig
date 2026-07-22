"""The custom-surface reference client (decision 0003).

A dependency-free (stdlib-only) peer for the channel gateway's GENERIC adapter
- the JSON-lines "custom interface" seam documented in
``services/channel_gateway/README.md``. Custom apps, the desktop familiar
addon, or the hey-nabu box can embed this class or mimic it line for line:

  - the gateway's generic adapter LISTENS on a localhost TCP port; a peer
    connects and writes one JSON object per line:
    ``{"id": "m1", "sender": "U-1", "text": "hi"}`` - each line becomes a
    governed work item via the kernel's ONE signed intake (``id`` is the
    delivery id the kernel's durable replay dedup keys on, so reuse a stable
    id scheme, never a random one per retry);
  - outbound replies arrive on the same connection as
    ``{"type": "outbound", "text": ..., "target": ...}`` lines.

This file is part of the SEVERED gateway service: stdlib only, no boltrig
imports (SEC-28), no secrets of its own (the connect-time secret stays
gateway-side; a peer only needs to reach the listener).

Demo: ``python -m clients.custom_surface`` (with a generic channel configured)
reads lines from stdin, sends them, and prints outbound replies.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

log = logging.getLogger("channel_gateway.clients.custom_surface")

OnOutbound = Callable[[dict[str, Any]], Awaitable[None]]


class CustomSurfaceClient:
    """One persistent JSON-lines peer to the generic adapter.

    ``surface_id`` is the ``sender`` stamped on inbound messages (the gateway
    maps it to a Principal via the channel's binding rows, exactly like a
    platform user id). ``on_outbound`` is awaited per outbound line.
    """

    def __init__(
        self, host: str = "127.0.0.1", port: int = 9090, *,
        surface_id: str = "custom-surface",
        on_outbound: OnOutbound | None = None,
    ) -> None:
        self._addr = (host, port)
        self._surface_id = surface_id
        self._on_outbound = on_outbound
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._recv_task: asyncio.Task | None = None
        self._seq = 0

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(*self._addr)
        self._recv_task = asyncio.create_task(self._receive_loop())

    async def send(self, text: str, *, message_id: str | None = None) -> None:
        """Send one inbound message. ``message_id`` defaults to a per-process
        monotonic id; pass your own stable id for dedup-across-restarts."""
        if self._writer is None:
            raise RuntimeError("connect() first")
        self._seq += 1
        line = json.dumps({
            "id": message_id or f"{self._surface_id}-{self._seq}",
            "sender": self._surface_id,
            "text": text,
        }, separators=(",", ":")) + "\n"
        self._writer.write(line.encode())
        await self._writer.drain()

    async def close(self) -> None:
        if self._recv_task is not None:
            self._recv_task.cancel()
            self._recv_task = None
        if self._writer is not None:
            self._writer.close()
            self._writer = None

    async def _receive_loop(self) -> None:
        try:
            while self._reader is not None:
                line = await self._reader.readline()
                if not line:
                    break
                try:
                    message = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    continue  # a malformed line is dropped, never fatal
                if isinstance(message, dict) and self._on_outbound is not None:
                    await self._on_outbound(message)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass


async def _print_outbound(message: dict[str, Any]) -> None:
    print(f"<< {message.get('text')}", flush=True)


async def _main() -> None:  # pragma: no cover - the interactive demo
    import sys

    client = CustomSurfaceClient(on_outbound=_print_outbound)
    await client.connect()
    print("custom-surface demo: type a line, Ctrl-D to quit", flush=True)
    loop = asyncio.get_running_loop()
    while True:
        text = await loop.run_in_executor(None, sys.stdin.readline)
        if not text:
            break
        await client.send(text.rstrip("\n"))
    await client.close()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_main())
