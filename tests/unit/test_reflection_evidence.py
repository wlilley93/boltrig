"""#29: reflection's silence is decidable - idle, broken, or off.

Reflection had never written a memory row anywhere, and nothing could say which
of three states that was: the feature disabled, no terminal work items (idle),
or every attempt dying inside a best-effort swallow at DEBUG (broken). The pump
now publishes a `reflection` receipt per throughput window WHEN ENABLED, and the
three states read off the receipts alone:

  no receipts                          -> disabled, or no pump runs
  receipts, item_count=0, succeeded    -> idle: nothing terminal to reflect
  receipts, succeeded=False            -> broken, and the pump log says why
                                          at WARNING (no longer DEBUG)
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

TENANT = "t-reflect"


class _Pump:
    """The surface run_pump_forever reads: run_once + the reflection window."""

    def __init__(self, store, *, reflect_enabled: bool) -> None:
        self._store = store
        self._reflect_enabled = reflect_enabled
        self.reflection_window = {"attempted": 0, "written": 0, "failed": 0}
        self.cycles = 0

    async def run_once(self, tenant_id):
        # Always idle, never blocking: a cap that parked run_once on a long
        # sleep starved the loop BEFORE the first window closed (40 cycles take
        # microseconds at interval=0) and every receipt assertion read empty.
        self.cycles += 1
        return False


class _Store:
    def __init__(self) -> None:
        self.receipts: list[dict] = []

    async def record_background_job_attempt(self, **kw):
        self.receipts.append(kw)


async def _run_windows(pump) -> None:
    """Drive run_pump_forever until a full window's receipts land, then cancel.

    The wait predicate must include the RECEIPT UNDER TEST: polling for only the
    pump receipt can cancel the loop between the pump write and the reflection
    write of the same window (10ms poll vs two awaited writes), which read as
    "reflection published nothing" on the first run of these tests.
    """
    import asyncio

    from boltrig.fleet import pump_progress

    def settled() -> bool:
        names = {r["job_name"] for r in pump._store.receipts}
        if "pump" not in names:
            return False
        return (not pump._reflect_enabled) or "reflection" in names

    task = asyncio.create_task(
        pump_progress.run_pump_forever(pump, TENANT, interval=0.0)
    )
    try:
        for _ in range(300):
            await asyncio.sleep(0.01)
            if settled():
                # one extra tick so a would-be extra write could land and fail
                # the disabled test rather than being cancelled away
                await asyncio.sleep(0.02)
                break
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def _window_short(monkeypatch) -> None:
    from boltrig.fleet import pump_progress

    monkeypatch.setattr(pump_progress, "window_for", lambda interval: 0.05)


async def test_enabled_and_idle_publishes_a_zero_count_success(monkeypatch) -> None:
    """IDLE is a receipt, not a silence: item_count=0, succeeded=True."""
    _window_short(monkeypatch)
    store = _Store()
    pump = _Pump(store, reflect_enabled=True)
    await _run_windows(pump)
    reflections = [r for r in store.receipts if r["job_name"] == "reflection"]
    assert reflections, "an enabled reflection must publish evidence every window"
    assert reflections[0]["item_count"] == 0
    assert reflections[0]["succeeded"] is True


async def test_disabled_publishes_nothing_under_the_reflection_name(monkeypatch) -> None:
    """The negative control: a receipt published unconditionally would report
    'idle' for a deployment where the feature does not even run."""
    _window_short(monkeypatch)
    store = _Store()
    pump = _Pump(store, reflect_enabled=False)
    await _run_windows(pump)
    assert [r for r in store.receipts if r["job_name"] == "reflection"] == []
    assert [r for r in store.receipts if r["job_name"] == "pump"], (
        "the pump's own receipt is unaffected"
    )


async def test_failures_in_the_window_publish_succeeded_false_and_reset(monkeypatch) -> None:
    """BROKEN is visible: any failed attempt makes the window's receipt
    succeeded=False, and the counters reset so the NEXT window stands alone."""
    _window_short(monkeypatch)
    store = _Store()
    pump = _Pump(store, reflect_enabled=True)
    pump.reflection_window.update(attempted=3, written=1, failed=2)
    await _run_windows(pump)
    reflections = [r for r in store.receipts if r["job_name"] == "reflection"]
    assert reflections[0]["succeeded"] is False
    assert reflections[0]["item_count"] == 1
    assert pump.reflection_window == {"attempted": 0, "written": 0, "failed": 0}


async def test_the_pump_counts_its_reflection_outcomes() -> None:
    """The counter half: _reflect increments attempted/written/failed, and a
    failure logs at WARNING - the swallow stays (a reflection failure must never
    fail the run) but the silence does not."""
    import logging

    from boltrig.fleet.pump import WorkPump
    from boltrig.models import WorkItem, WorkStatus
    from boltrig.store import InMemoryStore

    class _Kernel:
        def __init__(self, store, *, fail: bool) -> None:
            self.store = store
            self.fail = fail

        async def invoke(self, *a, **k):
            if self.fail:
                raise RuntimeError("memory backend down")
            return {"fact_ids": ["f1"]}

    item = WorkItem(
        id="w1", tenant_id=TENANT, source="internal", intent="x",
        confidence=1.0, convergent=True, status=WorkStatus.DONE,
    )

    ok = WorkPump(
        _Kernel(InMemoryStore(), fail=False), None, None, {}, reflect=True
    )
    await ok._reflect(item, "run-1", "done")
    assert ok.reflection_window == {"attempted": 1, "written": 1, "failed": 0}

    broken = WorkPump(
        _Kernel(InMemoryStore(), fail=True), None, None, {}, reflect=True
    )
    logger = logging.getLogger("boltrig.fleet.pump")
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[assignment]
    logger.addHandler(handler)
    try:
        await broken._reflect(item, "run-2", "done")
    finally:
        logger.removeHandler(handler)
    assert broken.reflection_window == {"attempted": 1, "written": 0, "failed": 1}
    assert any(
        r.levelno == logging.WARNING and "reflection failed" in r.getMessage()
        for r in records
    ), "a broken reflection must be loud, not DEBUG"
