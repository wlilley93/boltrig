"""The run/conversation event stream relay (Round Two, US-CONV-03/07).

Run events (text, reasoning, tool calls, sub-agents, HITL) are published to a
stream keyed by conversation/run id; the conversational endpoint subscribes and
forwards them to the client. A bounded per-stream backlog lets a dropped client
re-attach and receive the events it missed plus subsequent ones; the run keeps
producing regardless of whether anyone is listening (NFR-CONV-01, US-CONV-07).

In-memory and single-process by design (thin). A multi-replica deployment swaps
this for a Redis pub/sub behind the same interface.

Retention is bounded (NFR-CONV-02): each stream keeps at most ``backlog``
events, and once more than ``max_closed`` streams have been closed the oldest
closed ones are forgotten. A forgotten run's /v1/runs/{id}/events snapshot is
empty; the durable record is the persisted ConversationMessage.events and the
audit trail.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

_SENTINEL = object()  # end-of-stream marker placed on subscriber queues


class EventRelay:
    def __init__(self, backlog: int = 500, max_closed: int = 256) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = {}
        self._backlog: dict[str, list[dict[str, Any]]] = {}
        # insertion-ordered so eviction drops the oldest-closed streams first
        self._closed: dict[str, None] = {}
        self._max = backlog
        self._max_closed = max_closed

    def publish(self, stream_id: str, event: dict[str, Any]) -> None:
        """Record an event and fan it out to current subscribers (non-blocking)."""
        buf = self._backlog.setdefault(stream_id, [])
        buf.append(event)
        if len(buf) > self._max:
            del buf[: len(buf) - self._max]
        for q in list(self._subs.get(stream_id, ())):
            q.put_nowait(event)

    def close(self, stream_id: str) -> None:
        """Mark a stream complete; live subscribers end after draining.

        Retention (NFR-CONV-02): once more than ``max_closed`` streams are
        closed, the oldest closed ones are forgotten (backlog dropped).
        """
        self._closed[stream_id] = None
        for q in list(self._subs.get(stream_id, ())):
            q.put_nowait(_SENTINEL)
        while len(self._closed) > self._max_closed:
            self.forget(next(iter(self._closed)))

    async def subscribe(
        self, stream_id: str, *, replay: bool = True
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield events for a stream: the backlog first (re-attach), then live
        events until the stream is closed."""
        queue: asyncio.Queue = asyncio.Queue()
        self._subs.setdefault(stream_id, set()).add(queue)
        try:
            if replay:
                for event in list(self._backlog.get(stream_id, [])):
                    yield event
            if stream_id in self._closed:
                return
            while True:
                item = await queue.get()
                if item is _SENTINEL:
                    return
                yield item
        finally:
            subs = self._subs.get(stream_id)
            if subs is not None:
                subs.discard(queue)

    def forget(self, stream_id: str) -> None:
        """Drop a stream's backlog + state once it is fully consumed/persisted."""
        self._backlog.pop(stream_id, None)
        self._closed.pop(stream_id, None)
        self._subs.pop(stream_id, None)

    def snapshot(self, stream_id: str) -> list[dict[str, Any]]:
        """A copy of a stream's current backlog (a point-in-time read, no
        subscription). Used by the run-events endpoint for a non-following
        snapshot of what a run has emitted so far."""
        return list(self._backlog.get(stream_id, []))
