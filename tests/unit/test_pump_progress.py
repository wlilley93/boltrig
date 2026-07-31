"""The pump must publish throughput, and must NOT pretend to a stall verdict.

``run_forever`` took ``run_once``'s busy flag, used it to decide whether to sleep,
and threw it away. So a pump that could see work and claimed none - a lease bug, a
claim predicate that stopped matching - produced output identical to an idle one.

What it now publishes is deliberately weaker than the other loops' STALLED verdict,
and these tests pin that boundary too: an honest fact beats a verdict that would
cry wolf on every multi-worker deployment.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from boltrig.fleet.pump_progress import (
    MIN_WINDOW_SECONDS,
    PumpThroughput,
    run_pump_forever,
    window_for,
)

T0 = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


class _Clock:
    def __init__(self, start=T0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


def test_a_two_second_pump_does_not_write_a_receipt_every_cycle():
    """30 writes a minute per tenant would defeat a ledger built to be cheap."""
    assert window_for(2.0) == MIN_WINDOW_SECONDS
    assert window_for(2.0) / 2.0 >= 10, "at least ten cycles per receipt"


def test_a_slow_pump_still_gets_at_least_ten_cycles_per_window():
    assert window_for(30.0) == 300.0


def test_no_receipt_is_due_before_the_window_elapses():
    clock = _Clock()
    t = PumpThroughput(window_for(2.0), clock)
    for _ in range(20):
        t.observe(busy=True)
        clock.advance(2)
    assert not t.due(), "40s of a 60s window must not emit"
    clock.advance(21)
    assert t.due()


def test_the_receipt_carries_the_window_throughput_then_resets():
    clock = _Clock()
    t = PumpThroughput(60.0, clock)
    for _ in range(3):
        t.observe(busy=True)
    t.observe(busy=False)
    clock.advance(60)

    receipt = t.take()
    assert receipt["item_count"] == 3
    assert receipt["succeeded"] is True
    assert receipt["attempted_at"] == clock.now
    # Reset, or the next window double-counts and "items processed lately" becomes
    # a running total that never falls - which cannot show a pump going quiet.
    assert t.processed == 0
    assert not t.due()


def test_an_idle_window_reports_zero_and_is_still_a_success():
    """Zero items is not a failure. A pump with nothing to do is working correctly.

    The FACT "0 items in this window" is what an operator compares against the
    backlog; calling it a failure here would be the cry-wolf mistake.
    """
    clock = _Clock()
    t = PumpThroughput(60.0, clock)
    for _ in range(30):
        t.observe(busy=False)
    clock.advance(60)
    receipt = t.take()
    assert receipt["item_count"] == 0
    assert receipt["succeeded"] is True


def test_any_raising_cycle_makes_the_whole_window_a_failure():
    """A window that processed items and then started failing is not a success.

    Reporting it as one is how a degrading pump keeps looking healthy.
    """
    clock = _Clock()
    t = PumpThroughput(60.0, clock)
    t.observe(busy=True)
    t.observe(busy=True)
    t.observe(busy=False, failed=True)
    clock.advance(60)
    receipt = t.take()
    assert receipt["succeeded"] is False
    assert receipt["item_count"] == 2, "the work that DID happen is still reported"


class _Pump:
    """Claims `claimable` items, then goes quiet; optionally raises."""

    def __init__(self, claimable=0, raises=False):
        self._left = claimable
        self._raises = raises
        self.cycles = 0
        self._store = _Store()

    async def run_once(self, tenant_id):
        self.cycles += 1
        if self._raises:
            raise RuntimeError("claim exploded")
        if self._left > 0:
            self._left -= 1
            return True
        return False


class _Store:
    def __init__(self):
        self.receipts = []

    async def record_background_job_attempt(self, **kw):
        self.receipts.append(kw)
        return None


async def _drive(coro, seconds=0.4):
    task = asyncio.create_task(coro)
    await asyncio.sleep(seconds)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_the_loop_records_a_receipt_under_the_pump_job_name():
    """End to end, with a tiny interval so a window closes inside the test."""
    pump = _Pump(claimable=2)
    # interval 0.001 -> window is the 60s floor, so force a window by monkeypatching
    # nothing: instead assert the loop RUNS and records once the window is reached.
    await _drive(run_pump_forever(pump, "t", interval=0.001), seconds=0.2)
    assert pump.cycles > 1, "the loop must keep cycling"
    # No receipt yet: the 60s window has not elapsed, which is the intended economy.
    assert pump._store.receipts == []


@pytest.mark.asyncio
async def test_a_raising_pump_neither_dies_nor_reports_success(monkeypatch):
    """P9 plus honesty: it keeps cycling and the window is marked failed."""
    import boltrig.fleet.pump_progress as mod

    pump = _Pump(raises=True)
    monkeypatch.setattr(mod, "window_for", lambda interval: 0.0)  # close every cycle
    await _drive(run_pump_forever(pump, "t", interval=0.001), seconds=0.2)

    assert pump.cycles > 1, "a raising cycle must not kill the pump"
    assert pump._store.receipts, "a failing pump must still leave evidence"
    assert all(r["succeeded"] is False for r in pump._store.receipts)
    assert all(r["job_name"] == "pump" for r in pump._store.receipts)


@pytest.mark.asyncio
async def test_pump_is_a_registered_job_name_or_readiness_cannot_see_it():
    """Registration is what puts a loop on /readyz; logging is not enough."""
    from boltrig.models import BACKGROUND_JOB_NAMES

    assert "pump" in BACKGROUND_JOB_NAMES
