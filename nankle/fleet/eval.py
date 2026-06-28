"""EvalRunner - the evaluation harness (Round Three, Epic EVAL).

Runs an evaluation case through the real path: it spawns the target skill through
the kernel chokepoint under the INITIATOR's grants (a ceiling, so an eval can
never call a verb the initiator lacks - SEC-29), then checks the case assertions
and records an ``EvalRun`` (pass/score/detail) linked to the produced run id.

Assertions supported:
  * ``must_call``        verbs that must appear in the run's audit
  * ``must_not_call``    verbs that must NOT appear
  * ``forbidden_grants`` grants the child must NOT have received (no-escalation)
  * ``expect_output``    a subset that the run output must contain

It lives in the fleet layer (it orchestrates a spawn); the kernel imports nothing
from it. Offline-safe: with the script runtime it still runs and scores.
"""

from __future__ import annotations

import uuid

from nankle.models import EvalCase, EvalRun, GrantSet, InvocationContext, NankleError


class EvalRunner:
    def __init__(self, kernel, spawner) -> None:
        self._kernel = kernel
        self._spawner = spawner

    async def run_case(
        self, case: EvalCase, *, grants: GrantSet, actor: str = "eval"
    ) -> EvalRun:
        run_id = uuid.uuid4().hex
        ctx = InvocationContext(
            tenant_id=case.tenant_id, grants=grants, actor=actor, actor_tier="human",
            run_id=run_id, extra=dict(case.input or {}),
        )
        detail: dict = {}
        spawn_result: dict = {}
        try:
            spawn_result = await self._spawner.spawn(
                case.tenant_id, str(case.input.get("task", case.target_ref)),
                [case.target_ref], {}, ctx,
                partial_on_budget=True, grant_ceiling=grants,  # SEC-29: cap to initiator
            )
        except NankleError as exc:
            detail["spawn_error"] = exc.reason

        effective = set(spawn_result.get("effective_grants", []))
        called = {
            e.verb for e in await self._kernel.store.audit_query(case.tenant_id, run_id=run_id)
            if e.verb
        }
        a = case.assertions or {}
        checks: list[tuple[str, bool]] = []
        for verb in a.get("must_call", []):
            checks.append((f"must_call:{verb}", verb in called))
        for verb in a.get("must_not_call", []):
            checks.append((f"must_not_call:{verb}", verb not in called))
        for grant in a.get("forbidden_grants", []):
            # no-escalation: the child must NOT have been given this grant (SEC-29)
            checks.append((f"forbidden_grant:{grant}", grant not in effective))
        expect = a.get("expect_output")
        if isinstance(expect, dict):
            out = spawn_result.get("output", {}) or {}
            checks.append(("expect_output", all(out.get(k) == v for k, v in expect.items())))

        passed = all(ok for _, ok in checks) if checks else bool(spawn_result)
        score = (sum(1 for _, ok in checks if ok) / len(checks)) if checks else (1.0 if passed else 0.0)
        detail["checks"] = {name: ok for name, ok in checks}
        detail["effective_grants"] = sorted(effective)

        run = EvalRun(
            id=uuid.uuid4().hex, tenant_id=case.tenant_id, case_id=case.id,
            passed=passed, score=score, run_id=run_id, detail=detail,
        )
        await self._kernel.store.add_eval_run(run)
        return run
