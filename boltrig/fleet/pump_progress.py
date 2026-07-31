"""Windowed throughput evidence for the work pump.

WHY THE PUMP IS DIFFERENT FROM THE OTHER LOOPS. The anchor, distillation, HITL and
scheduler loops can count their own candidates, so they can escalate to STALLED:
"I could see N items and did none of them" is a judgeable statement. The pump
cannot honestly say that. ``claim_work_item`` returning None covers

  * genuinely nothing to do,
  * items legitimately leased by ANOTHER worker,
  * items parked AWAITING_HUMAN,
  * items scheduled for later,

and the claimable predicate lives inside that SQL. Any candidate count here would
either duplicate that predicate or inherit its bugs, and a naive
"backlog > 0 and not busy => STALLED" would fire on every multi-worker deployment.
A check that cries wolf gets ignored, which is worse than no check.

SO THIS PUBLISHES A FACT, NOT A VERDICT: "as of T, this pump instance had processed
N items in the last window". An operator (or a future probe) compares that against
the backlog and decides. What it removes is the thing that actually hid the failure
- silence. ``run_forever`` previously took ``run_once``'s busy flag, used it to
decide whether to sleep, and threw it away.

WINDOWED, because the pump cycles every 2 seconds. One receipt per cycle would be
30 writes a minute per tenant into a ledger whose whole purpose is to be cheap and
bounded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

MIN_WINDOW_SECONDS = 60.0
CYCLES_PER_WINDOW = 10


def window_for(interval: float) -> float:
    """The reporting window for a pump cycling every ``interval`` seconds.

    At least a minute, and at least ten cycles, so a slow pump still reports on a
    boundary it could plausibly reach.
    """
    return max(float(interval) * CYCLES_PER_WINDOW, MIN_WINDOW_SECONDS)


@dataclass
class PumpThroughput:
    """Accumulate cycle outcomes and hand back one receipt per window."""

    window_seconds: float
    clock: Callable[[], datetime]
    started_at: datetime = field(init=False)
    processed: int = 0
    failures: int = 0
    windows_reported: int = 0

    def __post_init__(self) -> None:
        self.started_at = self.clock()

    def observe(self, *, busy: bool, failed: bool = False) -> None:
        """Record one pump cycle."""
        if busy:
            self.processed += 1
        if failed:
            self.failures += 1

    def due(self, now: datetime | None = None) -> bool:
        at = now or self.clock()
        return (at - self.started_at).total_seconds() >= self.window_seconds

    def take(self, now: datetime | None = None) -> dict[str, Any]:
        """Close the window and return the receipt fields, resetting the counters.

        ``succeeded`` is False when ANY cycle in the window raised. A window that
        processed items and then started failing is not a success - reporting it as
        one is how a degrading pump would keep looking healthy.
        """
        at = now or self.clock()
        payload = {
            "attempted_at": at,
            "succeeded": self.failures == 0,
            "item_count": self.processed,
        }
        self.started_at = at
        self.processed = 0
        self.failures = 0
        self.windows_reported += 1
        return payload


async def run_pump_forever(pump: Any, tenant_id: str, *, interval: float = 2.0) -> None:
    """The pump's serving loop, instrumented. Cancellable; a bad cycle never kills it.

    Lives here rather than on ``WorkPump`` because pump.py is at its size ratchet and
    because the loop and the evidence it emits are one concern: the defect was
    precisely that the loop computed a progress signal and dropped it.
    """
    import asyncio
    import logging

    from boltrig.models.base import utcnow
    from boltrig.observability.background_jobs import (
        new_background_process_identity,
        record_background_attempt,
    )

    log = logging.getLogger("boltrig.fleet.pump")
    identity = new_background_process_identity()
    throughput = PumpThroughput(window_for(interval), utcnow)
    while True:
        failed = False
        try:
            busy = await pump.run_once(tenant_id)
        except asyncio.CancelledError:
            raise
        except Exception:  # a bad cycle never kills the pump (P9)
            log.exception("pump cycle failed; continuing")
            busy = False
            failed = True
        throughput.observe(busy=busy, failed=failed)
        if throughput.due():
            await record_background_attempt(
                pump._store,
                tenant_id=tenant_id,
                job_name="pump",
                process_instance_identity=identity,
                interval_seconds=throughput.window_seconds,
                **throughput.take(),
            )
        if not busy:
            await asyncio.sleep(interval)


__all__ = [
    "CYCLES_PER_WINDOW",
    "MIN_WINDOW_SECONDS",
    "PumpThroughput",
    "run_pump_forever",
    "window_for",
]
