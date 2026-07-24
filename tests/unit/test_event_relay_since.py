import pytest

from boltrig.kernel.events import EventRelay

TENANT = "t1"
RUN = "run-1"


def test_seq_is_monotonic_and_max_seq_tracks_it():
    r = EventRelay()
    assert r.max_seq(TENANT, RUN) == 0
    for i in range(5):
        r.publish(TENANT, RUN, {"type": "text_delta", "delta": str(i)})
    assert r.max_seq(TENANT, RUN) == 5


def test_snapshot_since_returns_only_events_after_cursor():
    r = EventRelay()
    for i in range(5):
        r.publish(TENANT, RUN, {"type": "text_delta", "delta": str(i)})  # seqs 1..5
    assert [e["delta"] for e in r.snapshot(TENANT, RUN)] == ["0", "1", "2", "3", "4"]
    assert [e["delta"] for e in r.snapshot(TENANT, RUN, since=3)] == ["3", "4"]
    assert r.snapshot(TENANT, RUN, since=5) == []
    assert r.snapshot(TENANT, RUN, since=99) == []  # stale cursor -> empty, no raise
    # event dicts are NOT mutated with a seq (chat/canvas frames stay identical)
    assert all("seq" not in e for e in r.snapshot(TENANT, RUN))


def test_since_survives_backlog_trim():
    r = EventRelay(backlog=3)
    for i in range(5):
        r.publish(TENANT, RUN, {"type": "text_delta", "delta": str(i)})  # seqs 1..5
    # backlog now holds seqs 3,4,5 (deltas "2","3","4"); max_seq still 5
    assert r.max_seq(TENANT, RUN) == 5
    assert [e["delta"] for e in r.snapshot(TENANT, RUN, since=3)] == ["3", "4"]
    # a cursor into the trimmed region just returns everything retained
    assert [e["delta"] for e in r.snapshot(TENANT, RUN, since=1)] == ["2", "3", "4"]


@pytest.mark.asyncio
async def test_subscribe_since_replays_only_after_cursor_then_live():
    r = EventRelay()
    for i in range(3):
        r.publish(TENANT, RUN, {"type": "text_delta", "delta": str(i)})  # seqs 1,2,3
    agen = r.subscribe(TENANT, RUN, replay=True, since=2)
    first = await agen.__anext__()  # replay: only seq>2 => delta "2"
    r.publish(TENANT, RUN, {"type": "text_delta", "delta": "live"})  # seq 4
    second = await agen.__anext__()
    r.close(TENANT, RUN)
    with pytest.raises(StopAsyncIteration):
        await agen.__anext__()
    assert [first["delta"], second["delta"]] == ["2", "live"]


def test_forget_resets_seq_state():
    r = EventRelay()
    r.publish(TENANT, RUN, {"type": "text_delta", "delta": "x"})
    r.forget(TENANT, RUN)
    assert r.max_seq(TENANT, RUN) == 0
    assert r.snapshot(TENANT, RUN) == []
