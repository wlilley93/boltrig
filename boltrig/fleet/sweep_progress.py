"""Make a stalled loop distinguishable from an idle one.

THE DEFECT THIS EXISTS FOR, measured on the beelink 2026-07-30. The session
distillation sweep wrote 20 of 89 conversations and then stopped forever:
container healthy, zero errors, and NO LOG OUTPUT AT ALL for seven minutes. The
only instrument that caught it was a person noticing a number had stopped moving.

Nothing was ever going to raise. A loop with nothing to do and a loop that has
stalled produce byte-identical logs, identical health checks, and identical error
counts of zero.

**COUNTING WORK DONE IS NOT ENOUGH, and that is the whole point of this module.**
The wedged sweep did zero work per cycle - exactly like an idle one. What separates
them is the pair: how many candidates the loop SAW, against how many it ACTED on.

    seen=0  acted=0   idle       - nothing to do, correct
    seen=69 acted=20  working    - draining a backlog
    seen=20 acted=0   STALLED    - it can see work and is not doing it
    seen=0  acted=0   ...but the backlog is non-zero elsewhere -> see `pending`

WHAT THIS CATCHES, AND WHAT IT DOES NOT. ``seen`` must be counted from the loop's
OWN selection, so this detects "can see work, does none" - a failing action, a
refused write, a lock never acquired. It does NOT detect a loop whose SELECTION
QUERY is wrong, because such a loop honestly reports seen=0 and is
indistinguishable from idle by these numbers alone.

That is not a hypothetical gap: the 2026-07-30 wedge was exactly that shape. The
selection filtered every candidate away and returned an empty list, so a
seen/acted pair would have said "idle" and been wrong.

``pending`` closes it, but ONLY if the caller obtains it INDEPENDENTLY of the
selection query. A pending count derived from the same query inherits the same
bug and turns this into a check that cannot fail. Callers that cannot compute an
independent count should pass ``pending=None`` and rely on an outside reader
instead - that is the job of the operator-facing probe, not of this counter.

Deliberately log-only for now. A durable progress ledger is a bigger change and a
separate decision; a structured line every cycle already turns silence into
evidence, and silence was the entire failure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger("boltrig.fleet.sweep_progress")

# A stall is only interesting if it PERSISTS. One cycle that sees work and does
# none can be a lock, a transient refusal, or a race. Three consecutive cycles is
# a pattern, and at a 300s interval that is 15 minutes - long before the seven
# minutes of silence that hid the real one, but not so twitchy that it cries wolf.
STALL_CYCLES = 3


@dataclass
class SweepProgress:
    """Per-cycle counters for one named loop, and the stall verdict they imply."""

    name: str
    cycles: int = 0
    last_seen: int = 0
    last_acted: int = 0
    total_acted: int = 0
    consecutive_stalled: int = 0

    def record(self, *, seen: int, acted: int, pending: int | None = None) -> str:
        """Record one cycle and return its verdict: idle, working, or stalled.

        The verdict is returned rather than only logged so a caller - a probe, a
        test, a future ledger - can act on it without parsing prose.
        """
        self.cycles += 1
        self.last_seen = seen
        self.last_acted = acted
        self.total_acted += acted

        if acted > 0:
            self.consecutive_stalled = 0
            verdict = "working"
        elif seen > 0 or (pending or 0) > 0:
            # It could see work, or work is waiting, and it did none.
            self.consecutive_stalled += 1
            verdict = "stalled" if self.consecutive_stalled >= STALL_CYCLES else "idle-ish"
        else:
            self.consecutive_stalled = 0
            verdict = "idle"

        detail = f"seen={seen} acted={acted} total={self.total_acted} cycle={self.cycles}"
        if pending is not None:
            detail += f" pending={pending}"

        if verdict == "stalled":
            # WARNING, not info: this is the state that hid for seven minutes.
            log.warning(
                "%s STALLED: %d consecutive cycles saw work and did none (%s)",
                self.name,
                self.consecutive_stalled,
                detail,
            )
        else:
            log.info("%s %s: %s", self.name, verdict, detail)
        return verdict
