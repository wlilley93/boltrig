"""The pending desktop-command registry (decision 0016, DH-1).

The kernel runs in a container that cannot reach the desktop compositor, so a
granted ``desktop.*`` dispatch cannot execute the window action itself. Instead
the adapter enqueues a command HERE and a host-side executor pulls it over the
authenticated ``/v1/hands`` surface, then posts a receipt. This registry is the
ONE hand-off point between the dispatch chokepoint and that pull surface: it is
created once at boot, hung on the kernel, and shared by the desktop adapter
(which creates + awaits commands) and the hands routes (which claim + complete
them). DH-1's "no side door" clause is that this registry is the only way a
window action leaves the kernel, and every entry in it was put there by a
granted, audited dispatch.

Everything runs on the kernel loop (the adapter handler and the route handlers
are all coroutines in the one process), so plain dicts + per-command
``asyncio.Event`` are sufficient - no locks. Claiming is mark-on-read: a command
is handed to exactly one executor poll, so a polled command can never be
executed twice by competing executors.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta
from typing import Any

from boltrig.models import utcnow

# A command the executor never claims (offline) or never completes (crashed
# mid-action) must not linger: after the TTL it is expired and swept, so a stale
# window action can never be picked up and executed late. The adapter's wait
# (8 s) is deliberately shorter than this, so a waiting dispatch always resolves
# before its command can be swept out from under it.
COMMAND_TTL_SECONDS = 30.0


class HandsRegistry:
    """In-memory pending-command store shared by the desktop adapter and routes."""

    def __init__(self, ttl_seconds: float = COMMAND_TTL_SECONDS) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._commands: dict[str, dict[str, Any]] = {}
        self._expiry: dict[str, datetime] = {}
        self._events: dict[str, asyncio.Event] = {}
        self._receipts: dict[str, dict[str, Any]] = {}

    def create(self, verb: str, args: dict[str, Any], run_id: str | None) -> dict[str, Any]:
        """Enqueue a command for the executor. Called only by the adapter handler,
        i.e. after the grant check + schema binding + audit of the dispatch."""
        cmd = {
            "id": uuid.uuid4().hex,
            "verb": verb,
            "args": args,
            "run_id": run_id,
            "queued_at": utcnow().isoformat(),
            "claimed": False,
        }
        self._commands[cmd["id"]] = cmd
        self._expiry[cmd["id"]] = utcnow() + self._ttl
        self._events[cmd["id"]] = asyncio.Event()
        return cmd

    def _sweep(self) -> None:
        """Drop expired commands (lazy GC, called from pending()). A swept command
        wakes any waiter with no receipt, which resolves as a timeout."""
        now = utcnow()
        for cmd_id, expires_at in list(self._expiry.items()):
            if expires_at <= now:
                self._drop(cmd_id)

    def _drop(self, cmd_id: str) -> None:
        self._commands.pop(cmd_id, None)
        self._expiry.pop(cmd_id, None)
        event = self._events.pop(cmd_id, None)
        if event is not None:
            event.set()  # wake a waiter; it finds no receipt and times out

    def pending(self) -> list[dict[str, Any]]:
        """Unclaimed, unexpired commands, oldest first."""
        self._sweep()
        return [c for c in self._commands.values() if not c["claimed"]]

    def claim(self, cmd_id: str) -> dict[str, Any] | None:
        """Mark a command claimed (mark-on-read) and return it, or None when the
        id is unknown, expired, or already claimed. After a successful claim no
        other poll can receive the command, so it cannot be double-executed."""
        self._sweep()
        cmd = self._commands.get(cmd_id)
        if cmd is None or cmd["claimed"]:
            return None
        cmd["claimed"] = True
        return cmd

    def complete(self, cmd_id: str, receipt: dict[str, Any]) -> bool:
        """Resolve a command with the executor's receipt. False for an unknown or
        expired id (the waiter already timed out, or the id was never ours)."""
        self._sweep()
        event = self._events.get(cmd_id)
        if event is None:
            return False
        self._receipts[cmd_id] = receipt
        event.set()
        return True

    async def wait(self, cmd_id: str, timeout: float) -> dict[str, Any] | None:
        """Await the receipt for a command. Returns the receipt, or None on
        timeout (the command is then expired and removed, so a late receipt is
        refused by complete())."""
        event = self._events.get(cmd_id)
        if event is None:
            return None
        try:
            await asyncio.wait_for(event.wait(), timeout)
        except TimeoutError:
            self._drop(cmd_id)
            return None
        receipt = self._receipts.pop(cmd_id, None)
        self._drop(cmd_id)
        return receipt
