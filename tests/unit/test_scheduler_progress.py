"""The workflow scheduler must distinguish "nothing due" from "not scheduling".

``reconcile_workflow_schedules`` returned the number of occurrences queued and the
loop discarded it, so a scheduler with due work that queues NOTHING - lease never
acquired, executor refusing, authority re-check failing closed - looked exactly
like one with nothing due. Both produced no output at all.

The due count is read off ``next_due_at`` on the schedule rows rather than from the
reconcile path, ON PURPOSE. A due count derived from the same logic inherits the
same bug and becomes a check that cannot fail.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from boltrig.fleet.sweep_progress import STALL_CYCLES, SweepProgress
from boltrig.workflows import scheduler_loop
from boltrig.workflows.scheduler_loop import (
    count_overdue,
    run_workflow_scheduler_forever,
)

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


@dataclass
class _Schedule:
    next_due_at: datetime | None


def test_overdue_counts_the_past_and_ignores_the_future():
    schedules = [
        _Schedule(NOW - timedelta(minutes=5)),
        _Schedule(NOW - timedelta(seconds=1)),
        _Schedule(NOW + timedelta(minutes=5)),
    ]
    assert count_overdue(schedules, NOW) == 2


def test_a_schedule_due_exactly_now_counts():
    assert count_overdue([_Schedule(NOW)], NOW) == 1


def test_an_uninitialised_schedule_is_not_overdue():
    """A schedule created this second has no next_due_at yet.

    Counting it would make the first cycle after any schedule is created report
    STALLED, and a check that cries wolf gets ignored.
    """
    assert count_overdue([_Schedule(None)], NOW) == 0


def test_a_naive_timestamp_is_treated_as_utc_not_raised_on():
    """A naive row must not take the janitor down inside its own reporting.

    Reporting that can raise is worse than no reporting: it converts a visible
    stall into a crashed loop.
    """
    assert count_overdue([_Schedule(NOW.replace(tzinfo=None) - timedelta(1))], NOW) == 1


def test_no_schedules_at_all_is_zero_not_an_error():
    assert count_overdue([], NOW) == 0
    assert count_overdue(None, NOW) == 0


def test_due_work_and_nothing_queued_escalates_to_stalled():
    """The state that was invisible."""
    progress = SweepProgress("workflow-scheduler")
    for _ in range(STALL_CYCLES - 1):
        assert progress.record(seen=3, acted=0) == "idle-ish"
    assert progress.record(seen=3, acted=0) == "stalled"


def test_nothing_due_stays_idle_however_long_it_runs():
    """The negative control: an idle scheduler must never be called stalled."""
    progress = SweepProgress("workflow-scheduler")
    verdicts = {progress.record(seen=0, acted=0) for _ in range(STALL_CYCLES + 3)}
    assert verdicts == {"idle"}


class _Store:
    def __init__(self, schedules):
        self._schedules = schedules
        self.reads = 0

    async def list_workflow_schedules(self, tenant_id):
        self.reads += 1
        return list(self._schedules)


async def _drive(loop_coro, cycles, interval=0.001):
    """Let the loop run a few cycles, then cancel it."""
    task = asyncio.create_task(loop_coro)
    await asyncio.sleep(interval * cycles * 6)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_the_loop_reports_a_stall_when_due_work_is_never_queued(monkeypatch, caplog):
    """End to end: due schedules, a reconcile that queues nothing, a WARNING.

    Before this, the same conditions produced silence.
    """
    import logging

    store = _Store([_Schedule(NOW - timedelta(minutes=1))] * 3)

    async def _queues_nothing(*a, **kw):
        return 0

    monkeypatch.setattr(scheduler_loop, "reconcile_workflow_schedules", _queues_nothing)

    with caplog.at_level(logging.INFO, logger="boltrig.fleet.sweep_progress"):
        await _drive(
            run_workflow_scheduler_forever(
                store, "t", None, executor=None, interval=0.001,
                now_fn=lambda: NOW,
            ),
            cycles=STALL_CYCLES + 1,
        )

    assert any("STALLED" in r.getMessage() for r in caplog.records), (
        "due schedules with nothing queued must reach a WARNING, not silence"
    )


@pytest.mark.asyncio
async def test_the_due_count_is_read_INDEPENDENTLY_of_the_reconcile(monkeypatch):
    """The loop must ask the store itself, not trust the reconcile's own view.

    If the due count came from the reconcile path, a reconcile that wrongly sees no
    due schedules would also report none due, and the pair would agree on being
    idle while work waited. The store read is what lets them disagree.
    """
    store = _Store([_Schedule(NOW - timedelta(minutes=1))])

    async def _queues_nothing(*a, **kw):
        return 0

    monkeypatch.setattr(scheduler_loop, "reconcile_workflow_schedules", _queues_nothing)
    await _drive(
        run_workflow_scheduler_forever(
            store, "t", None, executor=None, interval=0.001, now_fn=lambda: NOW,
        ),
        cycles=2,
    )
    assert store.reads >= 1, (
        "the loop never read the schedules itself, so its due count can only have "
        "come from the reconcile path it is supposed to be checking"
    )


@pytest.mark.asyncio
async def test_a_failing_reconcile_does_not_kill_the_loop(monkeypatch, caplog):
    """P9: a bad cycle is logged and the loop continues."""
    import logging

    store = _Store([_Schedule(None)])

    async def _explodes(*a, **kw):
        raise RuntimeError("executor unreachable")

    monkeypatch.setattr(scheduler_loop, "reconcile_workflow_schedules", _explodes)
    with caplog.at_level(logging.WARNING, logger="boltrig.workflows.scheduler_loop"):
        await _drive(
            run_workflow_scheduler_forever(
                store, "t", None, executor=None, interval=0.001, now_fn=lambda: NOW,
            ),
            cycles=2,
        )
    assert any("reconciliation failed" in r.getMessage() for r in caplog.records)
    assert store.reads >= 2, "the loop must keep cycling after a failure"
