"""The workflow scheduler's forever-loop, and the progress it publishes.

Split out of ``scheduler.py`` because that file sits at 398 of its 400-line
ratchet, so the loop could not gain reporting in place. The ratchet forcing an
extraction rather than a bigger file is the ratchet working.

WHAT WAS WRONG. ``reconcile_workflow_schedules`` returns the number of occurrences
it queued and the loop threw that number away, exactly as the anchor and
distillation loops did. So a scheduler with due schedules that queues NOTHING - a
lease never acquired, an executor refusing, an authority re-check failing closed -
produced identical output to a scheduler with nothing due: none at all.

THE INDEPENDENT SIGNAL, and why it is read separately. ``SweepProgress`` can only
tell "saw work and did none" from "had nothing to do" if the two numbers come from
different places. A due-count derived from the reconcile path would inherit any bug
in that path and turn this into a check that cannot fail. So the loop reads
``next_due_at`` off the schedule rows itself: that is the stored desire, written by
whoever created the schedule, and it is true independently of whether the
reconcile logic can see it.

  overdue=0 queued=0   idle       - nothing due, correct
  overdue=3 queued=3   working
  overdue=3 queued=0   STALLED    - work is due and the scheduler is not doing it
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from typing import Any

from boltrig.fleet.sweep_progress import SweepProgress

from .scheduler import reconcile_workflow_schedules

log = logging.getLogger("boltrig.workflows.scheduler_loop")


def count_overdue(schedules: Any, now: datetime) -> int:
    """Schedules whose stored ``next_due_at`` has passed.

    Deliberately dumb and deliberately NOT the scheduler's own due calculation. Its
    job is to disagree with the reconcile path when that path is broken, which it
    cannot do if it shares the reasoning.

    A schedule with no ``next_due_at`` has never been initialised, so it is not yet
    overdue and is not counted: counting it would make the first cycle after any
    schedule is created look stalled.
    """
    total = 0
    for schedule in schedules or ():
        due_at = getattr(schedule, "next_due_at", None)
        if due_at is None:
            continue
        if due_at.tzinfo is None:  # a naive row must not raise here
            due_at = due_at.replace(tzinfo=timezone.utc)
        if due_at <= now:
            total += 1
    return total


async def run_workflow_scheduler_forever(
    store: Any,
    tenant_id: str,
    workflows: Any,
    *,
    executor: Any,
    interval: float,
    worker_id: str | None = None,
    now_fn: Any = None,
) -> None:
    """Reconcile due schedules forever, saying each cycle what it saw and did.

    A bad cycle is logged and the loop continues (P9); cancellation propagates.
    """
    from boltrig.observability.background_jobs import (
        new_background_process_identity,
        record_background_attempt,
    )

    clock = now_fn or (lambda: datetime.now(timezone.utc))
    progress = SweepProgress("workflow-scheduler")
    # The durable half: SweepProgress logs, and a log answers no operator query and
    # survives no restart. /readyz reads the receipt ledger.
    identity = new_background_process_identity()
    while True:
        attempted_at = clock()
        succeeded = True
        queued = 0
        try:
            now = clock()
            # Read the desire BEFORE reconciling, so a reconcile that consumes the
            # due rows cannot make its own inaction look like there was nothing due.
            overdue = count_overdue(
                await store.list_workflow_schedules(tenant_id), now
            )
            queued = await reconcile_workflow_schedules(
                store,
                tenant_id,
                workflows,
                executor=executor,
                worker_id=worker_id,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            succeeded = False
            log.warning("workflow schedule reconciliation failed", exc_info=True)
        else:
            progress.record(seen=overdue, acted=queued)
        # Best-effort evidence, exactly as the retention janitor does it: it can
        # never change the outcome, and a failed write must not stall the loop.
        await record_background_attempt(
            store,
            tenant_id=tenant_id,
            job_name="workflow_scheduler",
            process_instance_identity=identity,
            interval_seconds=interval,
            attempted_at=attempted_at,
            succeeded=succeeded,
            item_count=queued,
        )
        await asyncio.sleep(interval)


__all__ = ["count_overdue", "run_workflow_scheduler_forever"]
