"""Harvest free feedback into reuse WEIGHTING, never into authority (COUNTY 5).

Two signals fall out of everyday use and are worth learning from:

  * a regenerate that SUPERSEDES an assistant reply (``superseded_by`` set) is a
    NEGATIVE signal for whatever produced that reply;
  * a HITL answer is an explicit human verdict - an approval is an ENDORSEMENT, a
    rejection is a BLOCK signal.

Both are fed into the reuse weighting two ways, and ONLY these two ways:

  * ``harvest_reuse_signal`` reweights memory through ``memory.improve`` - the
    reweight-only verb that, by construction, accepts no scope/grant/authority
    argument (SEC-84). It runs THROUGH the kernel chokepoint under the caller's
    own context, so the memory governance screens still apply;
  * ``apply_promotion_signal`` nudges a workflow's bounded reuse score in [-1, 1]
    on its :class:`~boltrig.models.WorkflowPromotion` record. It never changes the
    promotion STATE (only the eval gate does) and never touches grants.

Everything here is BEST-EFFORT: a signal-harvest failure is swallowed so it can
never fail the run that produced the signal (P9).
"""

from __future__ import annotations

import logging
from typing import Any

from boltrig.models import PromotionState, WorkflowPromotion

log = logging.getLogger("boltrig.workflows.signals")

# Polarity -> (a bland signal word for memory.improve, a bounded score delta).
# The words are deliberately plain so they clear the memory injection screen; the
# deltas are small so no single signal dominates the eval-gated state base.
_POLARITY: dict[str, tuple[str, float]] = {
    "endorsement": ("endorsement", +0.5),   # a HITL approval
    "block": ("block", -0.5),                # a HITL rejection
    "regression": ("regression", -0.25),     # a regenerate superseded a reply
    "reinforcement": ("reinforcement", +0.25),
}


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, value))


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
    word, _ = _POLARITY.get(polarity, ("signal", 0.0))
    try:
        await kernel.invoke(
            "memory", "memory.improve",
            {"signal": f"{kind}:{word}", "target": str(target)}, context,
        )
    except Exception:  # a harvest failure never fails the run that produced it (P9)
        log.debug("reuse-signal harvest failed (kind=%s); continuing", kind, exc_info=True)


async def apply_promotion_signal(
    store: Any, tenant_id: str, workflow_id: str, *, polarity: str,
) -> WorkflowPromotion | None:
    """Nudge a workflow's bounded reuse score from a free signal (ranking only).

    Adjusts ``WorkflowPromotion.score`` by a small bounded delta, clamped to
    [-1, 1], leaving the eval-gated STATE untouched (only the promoter changes
    state) and never touching grants/scope/tier. Creates a CANDIDATE record if the
    workflow has none yet. Best-effort: returns ``None`` on any failure (P9).
    """
    _, delta = _POLARITY.get(polarity, ("", 0.0))
    if not delta:
        return None
    try:
        existing = await store.get_workflow_promotion(tenant_id, workflow_id)
        state = existing.state if existing is not None else PromotionState.CANDIDATE
        score = _clamp((existing.score if existing is not None else 0.0) + delta)
        eval_run_id = existing.eval_run_id if existing is not None else None
        promotion = WorkflowPromotion(
            workflow_id=workflow_id, tenant_id=tenant_id, state=state,
            score=score, eval_run_id=eval_run_id,
        )
        await store.upsert_workflow_promotion(promotion)
        return promotion
    except Exception:  # best-effort; a signal is never load-bearing (P9)
        log.debug("promotion-signal nudge failed for %s; continuing", workflow_id,
                  exc_info=True)
        return None
