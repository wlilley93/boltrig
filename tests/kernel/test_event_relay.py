"""EventRelay bounded retention (NFR-CONV-02): closed streams are forgotten
past the retention cap; open streams and recently closed streams are kept."""

import pytest

from boltrig.kernel.events import EventRelay


@pytest.mark.kernel
@pytest.mark.invariant("NFR-CONV-02")
async def test_closed_streams_are_bounded_and_oldest_forgotten():
    n = 3
    relay = EventRelay(max_closed=n)
    scoped = relay.for_tenant("acme")
    for i in range(n + 1):
        sid = f"run-{i}"
        scoped.publish(sid, {"delta": str(i)})
        scoped.close(sid)
    # the oldest closed stream is forgotten: backlog and closed-marker gone
    assert scoped.snapshot("run-0") == []
    assert ("acme", "run-0") not in relay._backlog
    assert ("acme", "run-0") not in relay._closed
    # the relay's per-stream state stays bounded at the cap
    assert len(relay._closed) <= n and len(relay._backlog) <= n
    # a recently closed stream still replays its backlog to a re-attach
    events = [e async for e in scoped.subscribe("run-3", replay=True)]
    assert events == [{"delta": "3"}]


@pytest.mark.kernel
@pytest.mark.invariant("NFR-CONV-02")
async def test_open_streams_are_never_evicted():
    relay = EventRelay(max_closed=2)
    scoped = relay.for_tenant("acme")
    scoped.publish("open-run", {"delta": "live"})
    for i in range(5):  # churn well past the cap
        sid = f"run-{i}"
        scoped.publish(sid, {"delta": str(i)})
        scoped.close(sid)
    # the open (never-closed) stream keeps its backlog and is not marked closed
    assert scoped.snapshot("open-run") == [{"delta": "live"}]
    assert ("acme", "open-run") not in relay._closed
