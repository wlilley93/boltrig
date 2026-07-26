"""The run/conversation event stream relay (Round Two, US-CONV-03/07).

Run events (text, reasoning, tool calls, sub-agents, HITL) are published to a
stream keyed by tenant plus conversation/run id; the conversational endpoint
subscribes and forwards them to the client. A bounded per-stream backlog lets a
dropped client re-attach and receive the events it missed plus subsequent ones;
the run keeps producing regardless of whether anyone is listening
(NFR-CONV-01, US-CONV-07).

In-memory and single-process by design (thin). A multi-replica deployment swaps
this for a Redis pub/sub behind the same interface.

Retention is bounded (NFR-CONV-02): each stream keeps at most ``backlog``
events, and once more than ``max_closed`` streams have been closed the oldest
closed ones are forgotten. A forgotten run's /v1/runs/{id}/events snapshot is
empty; the durable record is the persisted ConversationMessage.events and the
audit trail.

Each event is assigned a per-stream monotonic ``seq`` at publish time, kept beside
it in the backlog (never written into the event dict, so chat/canvas frames stay
byte-identical). A caller that holds a cursor can resume with ``since=<seq>`` and
skip everything it has already seen (GAP G5); the seq stays stable across the
bounded buffer's trims where a positional index would shift.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

_SENTINEL = object()  # end-of-stream marker placed on subscriber queues
_StreamKey = tuple[str, str]


class TenantEventRelay:
    """A tenant-bound relay view for trusted turn-executor integrations.

    The legacy executor-facing shape stays ``publish(run_id, event)`` while the
    tenant namespace is fixed at construction and cannot be selected from an
    attacker-controlled run id.
    """

    def __init__(self, relay: EventRelay, tenant_id: str) -> None:
        self._relay = relay
        self._tenant_id = tenant_id

    def publish(self, stream_id: str, event: dict[str, Any]) -> None:
        self._relay.publish(self._tenant_id, stream_id, event)

    def close(self, stream_id: str) -> None:
        self._relay.close(self._tenant_id, stream_id)

    def reopen(self, stream_id: str) -> None:
        self._relay.reopen(self._tenant_id, stream_id)

    def subscribe(
        self, stream_id: str, *, replay: bool = True, since: int | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        return self._relay.subscribe(
            self._tenant_id, stream_id, replay=replay, since=since
        )

    def forget(self, stream_id: str) -> None:
        self._relay.forget(self._tenant_id, stream_id)

    def snapshot(
        self, stream_id: str, *, since: int | None = None
    ) -> list[dict[str, Any]]:
        return self._relay.snapshot(self._tenant_id, stream_id, since=since)

    def max_seq(self, stream_id: str) -> int:
        return self._relay.max_seq(self._tenant_id, stream_id)


class EventRelay:
    def __init__(self, backlog: int = 500, max_closed: int = 256) -> None:
        self._subs: dict[_StreamKey, set[asyncio.Queue]] = {}
        # each backlog entry is (seq, event): the per-stream monotonic seq lets a
        # caller resume after events it has already seen (?since=<seq>, GAP G5)
        # even after the bounded buffer has trimmed its oldest entries - a plain
        # list index would shift on every trim; the seq never does.
        self._backlog: dict[_StreamKey, list[tuple[int, dict[str, Any]]]] = {}
        # insertion-ordered so eviction drops the oldest-closed streams first
        self._closed: dict[_StreamKey, None] = {}
        # per-stream monotonic seq counter (last assigned), kept until forget so a
        # resumed run never re-uses a seq a live cursor already passed.
        self._seq: dict[_StreamKey, int] = {}
        self._max = backlog
        self._max_closed = max_closed

    @staticmethod
    def _key(tenant_id: str, stream_id: str) -> _StreamKey:
        if not tenant_id or not stream_id:
            raise ValueError("tenant_id and stream_id are required")
        return tenant_id, stream_id

    def for_tenant(self, tenant_id: str) -> TenantEventRelay:
        """Return a relay view permanently bound to one non-empty tenant."""
        self._key(tenant_id, "namespace-check")
        return TenantEventRelay(self, tenant_id)

    def publish(self, tenant_id: str, stream_id: str, event: dict[str, Any]) -> None:
        """Record an event and fan it out to current subscribers (non-blocking).

        Each event is assigned the stream's next monotonic seq, stored alongside it
        in the backlog. The seq stays INTERNAL to the relay (never written into the
        event dict), so the chat SSE and run-canvas frames are byte-identical to
        before; only ``snapshot``/``subscribe``'s ``since`` filter and ``max_seq``
        read it.
        """
        key = self._key(tenant_id, stream_id)
        seq = self._seq.get(key, 0) + 1
        self._seq[key] = seq
        buf = self._backlog.setdefault(key, [])
        buf.append((seq, event))
        if len(buf) > self._max:
            del buf[: len(buf) - self._max]
        for q in list(self._subs.get(key, ())):
            q.put_nowait(event)

    def close(self, tenant_id: str, stream_id: str) -> None:
        """Mark a stream complete; live subscribers end after draining.

        Retention (NFR-CONV-02): once more than ``max_closed`` streams are
        closed, the oldest closed ones are forgotten (backlog dropped).
        """
        key = self._key(tenant_id, stream_id)
        self._closed[key] = None
        for q in list(self._subs.get(key, ())):
            q.put_nowait(_SENTINEL)
        while len(self._closed) > self._max_closed:
            self.forget(*next(iter(self._closed)))

    def reopen(self, tenant_id: str, stream_id: str) -> None:
        """Re-open a closed stream so a continuation can be published to it.

        A chat turn closes its stream when the turn ends (``chat._safe_exec``), and
        ``subscribe`` returns IMMEDIATELY for a closed key - so a write held for a
        human decision, resumed minutes later, would publish its result into a
        stream no new subscriber could ever read from. Dropping the key from
        ``_closed`` is the whole operation: the backlog stays (a client that
        re-attaches still gets what it missed), and ``_seq`` is deliberately NOT
        touched - per-stream monotonicity across a resumption is what keeps a
        ``?since=<seq>`` cursor safe, so a resumed stream must never re-issue a seq
        a live cursor has already passed.
        """
        self._closed.pop(self._key(tenant_id, stream_id), None)

    async def subscribe(
        self,
        tenant_id: str,
        stream_id: str,
        *,
        replay: bool = True,
        since: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield events for a stream: the backlog first (re-attach), then live
        events until the stream is closed.

        ``since`` (GAP G5): when given, the replayed backlog is limited to events
        whose seq is strictly greater than ``since`` - a caller re-attaching after a
        known cursor skips everything it has already seen. Live events are always
        newer than any backlog seq (monotonic per stream), so they are never
        filtered; ``since`` only ever narrows the REPLAY, never the live tail.
        """
        key = self._key(tenant_id, stream_id)
        queue: asyncio.Queue = asyncio.Queue()
        self._subs.setdefault(key, set()).add(queue)
        try:
            if replay:
                for seq, event in list(self._backlog.get(key, [])):
                    if since is None or seq > since:
                        yield event
            if key in self._closed:
                return
            while True:
                item = await queue.get()
                if item is _SENTINEL:
                    return
                yield item
        finally:
            subs = self._subs.get(key)
            if subs is not None:
                subs.discard(queue)

    def forget(self, tenant_id: str, stream_id: str) -> None:
        """Drop a stream's backlog + state once it is fully consumed/persisted."""
        key = self._key(tenant_id, stream_id)
        self._backlog.pop(key, None)
        self._closed.pop(key, None)
        self._subs.pop(key, None)
        self._seq.pop(key, None)

    def snapshot(
        self, tenant_id: str, stream_id: str, *, since: int | None = None
    ) -> list[dict[str, Any]]:
        """A copy of a stream's current backlog (a point-in-time read, no
        subscription). ``since`` (GAP G5) returns only events after that seq; None
        returns the whole retained backlog (unchanged default)."""
        buf = self._backlog.get(self._key(tenant_id, stream_id), [])
        if since is None:
            return [event for _seq, event in buf]
        return [event for seq, event in buf if seq > since]

    def max_seq(self, tenant_id: str, stream_id: str) -> int:
        """The highest seq assigned to this stream so far (0 if it has published
        nothing). A caller captures this at a boundary and passes it back as
        ?since=<seq> to resume the stream after exactly what it has seen (GAP G5)."""
        return self._seq.get(self._key(tenant_id, stream_id), 0)
