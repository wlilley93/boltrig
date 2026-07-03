"""Eval-gated promotion: raise a workflow's REUSE ranking, never its authority.

The self-improvement flywheel may make a good workflow more LIKELY to be reused,
but it must never let provenance widen what that workflow is permitted to do
([2026] VJS-COUNTY 5). This module is the promotion half of that rail:

  * a GENERATED / LEARNED workflow starts as a promotion CANDIDATE - reusable but
    not preferred;
  * :class:`WorkflowPromoter` runs the candidate through the real
    :class:`~boltrig.fleet.eval.EvalRunner` against its eval cases. The eval runs
    THROUGH the kernel chokepoint under the INITIATOR's grants as a ceiling
    (``EvalRunner`` already caps the child to those grants, SEC-29), so promotion
    invents no new authority path and can never call a verb the initiator lacks;
  * on PASS the workflow is marked PROMOTED so the matcher PREFERS it among
    equally-matching workflows; on a later FAIL it is DEMOTED so the matcher stops
    preferring it.

Promotion state is stored as a :class:`~boltrig.models.WorkflowPromotion` record
keyed by workflow id - NOT a field on ``WorkflowDefinition`` - and it carries no
grant / scope / tier. It changes RANKING only. Execution authority still comes
solely from the caller ceiling at dispatch.
"""

from __future__ import annotations

import logging
from typing import Any

from boltrig.models import GrantSet, PromotionState, WorkflowPromotion

log = logging.getLogger("boltrig.workflows.promotion")


def _clamp(value: float) -> float:
    """Bound a reuse weight to [-1, 1] (it is a ranking nudge, not a score)."""
    return max(-1.0, min(1.0, value))


def _state_base(state: PromotionState) -> float:
    """The eval-gated base weight a promotion state contributes to ranking."""
    if state is PromotionState.PROMOTED:
        return 1.0
    if state is PromotionState.DEMOTED:
        return -1.0
    return 0.0


def reuse_weight(promotion: WorkflowPromotion | None) -> float:
    """The bounded reuse weight in [-1, 1] the matcher reads (ranking ONLY).

    Combines the eval-gated state base (PROMOTED +1, DEMOTED -1, CANDIDATE 0) with
    the accumulated harvested-signal score, clamped to [-1, 1]. No workflow gets
    an authority boost - this only tunes how likely it is to be REUSED. Absence of
    a record is a neutral 0, so behaviour is unchanged where nothing was promoted.
    """
    if promotion is None:
        return 0.0
    return _clamp(_state_base(promotion.state) + promotion.score)


class WorkflowPromoter:
    """Run a candidate workflow's eval cases and set its reuse-ranking state.

    ``store`` supplies the eval cases and persists the promotion record;
    ``eval_runner`` is the shared :class:`~boltrig.fleet.eval.EvalRunner` - the one
    harness that spawns through the chokepoint under the initiator ceiling. This
    class never touches grants, scope, or tier: it only writes a ranking record.
    """

    def __init__(self, store: Any, eval_runner: Any) -> None:
        self._store = store
        self._eval_runner = eval_runner

    async def _cases_for(self, tenant_id: str, workflow_id: str) -> list[Any]:
        cases = await self._store.list_eval_cases(tenant_id)
        return [
            c for c in cases
            if c.target_kind == "workflow" and c.target_ref == workflow_id
        ]

    async def _record(
        self, tenant_id: str, workflow_id: str, state: PromotionState,
        *, eval_run_id: str | None,
    ) -> WorkflowPromotion:
        # Preserve any accumulated signal score across a state change: the eval
        # gate owns STATE, harvested signals own SCORE (see workflows.signals).
        existing = await self._store.get_workflow_promotion(tenant_id, workflow_id)
        score = existing.score if existing is not None else 0.0
        promotion = WorkflowPromotion(
            workflow_id=workflow_id, tenant_id=tenant_id, state=state,
            score=score, eval_run_id=eval_run_id,
        )
        await self._store.upsert_workflow_promotion(promotion)
        return promotion

    async def evaluate(
        self, tenant_id: str, workflow_id: str, *, grants: GrantSet, actor: str = "promotion",
    ) -> WorkflowPromotion:
        """Eval-gate a candidate and set PROMOTED / DEMOTED / CANDIDATE.

        Runs every eval case targeting ``workflow_id`` through the EvalRunner under
        ``grants`` as a ceiling (SEC-29 - the child can never exceed the initiator).
        PASS (all cases pass) -> PROMOTED; any FAIL -> DEMOTED; no eval cases ->
        stays a CANDIDATE (a candidate must pass an eval before it is preferred, so
        an un-evaluated workflow is never promoted).
        """
        cases = await self._cases_for(tenant_id, workflow_id)
        if not cases:
            return await self._record(
                tenant_id, workflow_id, PromotionState.CANDIDATE, eval_run_id=None,
            )
        runs = []
        for case in cases:
            runs.append(
                await self._eval_runner.run_case(case, grants=grants, actor=actor)
            )
        passed = all(r.passed for r in runs)
        state = PromotionState.PROMOTED if passed else PromotionState.DEMOTED
        return await self._record(
            tenant_id, workflow_id, state, eval_run_id=runs[-1].id,
        )
