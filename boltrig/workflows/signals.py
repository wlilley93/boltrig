"""Harvest free feedback into reuse WEIGHTING, never into authority (COUNTY 5).

Two signals fall out of everyday use and are worth learning from:

  * a regenerate that SUPERSEDES an assistant reply (``superseded_by`` set) is a
    NEGATIVE signal for whatever produced that reply;
  * a HITL answer is an explicit human verdict - an approval is an ENDORSEMENT, a
    rejection is a BLOCK signal.

There is exactly ONE way either is fed back: ``harvest_reuse_signal`` reweights
memory through ``memory.improve`` - the reweight-only verb that, by construction,
accepts no scope/grant/authority argument (SEC-84). It runs THROUGH the kernel
chokepoint under the caller's own context, so the memory governance screens still
apply.

There used to be a second way, a bounded score nudge on a stored workflow
promotion record. It is gone: [2026] VJS-CC-BOLTRIG-WORKFLOW-PROMOTION-TRIGGER-001
found the promotion subsystem's consumer transitively unreachable from any
production entry point and retired the whole of it, D3.

Everything here is BEST-EFFORT: a signal-harvest failure is swallowed so it can
never fail the run that produced the signal (P9).
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("boltrig.workflows.signals")

# Polarity -> a bland signal word for memory.improve. The words are deliberately
# plain so they clear the memory injection screen.
_POLARITY: dict[str, str] = {
    "endorsement": "endorsement",     # a HITL approval
    "block": "block",                 # a HITL rejection
    "regression": "regression",       # a regenerate superseded a reply
    "reinforcement": "reinforcement",
}


async def harvest_reuse_signal(
    kernel: Any, context: Any, *, target: str, polarity: str, kind: str,
) -> None:
    """Reweight memory from a free signal via ``memory.improve`` (reweight-only).

    Best-effort and reweight-ONLY: it dispatches ``memory.improve`` through the
    chokepoint under ``context`` (the caller ceiling), passing just a signal string
    and a target. The verb carries no grant/scope/authority, so this can only
    change ranking/likelihood, never what anyone may do (COUNTY 5). Any failure -
    a missing grant, the memory adapter down - is swallowed (P9).
    """
    word = _POLARITY.get(polarity, "signal")
    try:
        await kernel.invoke(
            "memory", "memory.improve",
            {"signal": f"{kind}:{word}", "target": str(target)}, context,
        )
    except Exception:  # a harvest failure never fails the run that produced it (P9)
        log.debug("reuse-signal harvest failed (kind=%s); continuing", kind, exc_info=True)
