"""EvalRunner - the evaluation harness (Round Three, Epic EVAL).

Runs an evaluation case through the target's real path: skills use the spawner
and workflows use the governed workflow interpreter. Both execute under the
INITIATOR's grants (a ceiling, so an eval can never call a verb the initiator
lacks - SEC-29), then the runner checks the case assertions and records an
``EvalRun`` (pass/score/detail) linked to the produced run id.

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
from dataclasses import replace
from typing import Any

from boltrig.models import (
    BoltrigError,
    EVAL_TARGET_KINDS,
    EvalCase,
    EvalCaseArchived,
    EvalRun,
    GrantSet,
    InvocationContext,
)


class EvalRunner:
    def __init__(
        self,
        kernel: Any,
        spawner: Any,
        *,
        workflows: Any | None = None,
    ) -> None:
        self._kernel = kernel
        self._spawner = spawner
        self._workflows = workflows

    async def _active_case(self, case: EvalCase) -> EvalCase:
        """Refresh lifecycle state so stale callers cannot run an archived case."""
        persisted = await self._kernel.store.get_eval_case(case.tenant_id, case.id)
        current = persisted or case
        if not current.is_active:
            raise EvalCaseArchived("evaluation case is archived")
        return current

    async def _run_skill(
        self,
        case: EvalCase,
        grants: GrantSet,
        context: InvocationContext,
    ) -> tuple[dict[str, Any], GrantSet, bool, dict[str, Any]]:
        result: dict[str, Any] = {}
        detail: dict[str, Any] = {}
        try:
            result = await self._spawner.spawn(
                case.tenant_id,
                str(case.input.get("task", case.target_ref)),
                [case.target_ref],
                {},
                context,
                partial_on_budget=True,
                grant_ceiling=grants,  # SEC-29: cap to initiator
            )
        except BoltrigError as exc:
            detail["target_error"] = exc.reason
        authority = GrantSet.of(list(result.get("effective_grants", [])))
        return result, authority, bool(result), detail

    async def _run_workflow(
        self,
        case: EvalCase,
        grants: GrantSet,
        context: InvocationContext,
    ) -> tuple[dict[str, Any], GrantSet, bool, dict[str, Any]]:
        detail: dict[str, Any] = {}
        if self._workflows is None:
            return {}, grants, False, {"target_error": "workflow_evaluator_unavailable"}
        try:
            output = await self._workflows.execute(
                case.tenant_id, case.target_ref, dict(case.input or {}), context
            )
        except LookupError:
            return {}, grants, False, {"target_error": "target_not_found"}
        except PermissionError:
            return {}, grants, False, {"target_error": "target_unavailable"}
        detail["workflow_status"] = output.get("status")
        result = {"output": output, "effective_grants": list(grants.allow)}
        return result, grants, output.get("status") == "completed", detail

    async def _execute_target(
        self,
        case: EvalCase,
        grants: GrantSet,
        context: InvocationContext,
    ) -> tuple[dict[str, Any], GrantSet, bool, dict[str, Any]]:
        if case.target_kind not in EVAL_TARGET_KINDS:
            # Legacy/directly-forged rows execute nothing. New authoring is
            # schema-closed to EVAL_TARGET_KINDS.
            return {}, GrantSet.of([]), False, {"target_error": "unsupported_target_kind"}
        if case.target_kind == "skill":
            return await self._run_skill(case, grants, context)
        # WorkflowLibrary.execute is the canonical single-shot workflow path:
        # each capability step still enters kernel.invoke under this ceiling.
        return await self._run_workflow(case, grants, context)

    async def _checks(
        self,
        case: EvalCase,
        run_id: str,
        result: dict[str, Any],
        authority: GrantSet,
    ) -> list[tuple[str, bool]]:
        called = {
            event.verb
            for event in await self._kernel.store.audit_query(case.tenant_id, run_id=run_id)
            if event.verb
        }
        assertions = case.assertions or {}
        checks = [(f"must_call:{verb}", verb in called) for verb in assertions.get("must_call", [])]
        checks.extend(
            (f"must_not_call:{verb}", verb not in called)
            for verb in assertions.get("must_not_call", [])
        )
        checks.extend(
            (
                f"forbidden_grant:{grant}",
                not authority.permits(str(grant)),
            )
            for grant in assertions.get("forbidden_grants", [])
        )
        expected = assertions.get("expect_output")
        if isinstance(expected, dict):
            output = result.get("output", {}) or {}
            checks.append(
                (
                    "expect_output",
                    all(output.get(key) == value for key, value in expected.items()),
                )
            )
        return checks

    @staticmethod
    def _verdict(target_ok: bool, checks: list[tuple[str, bool]]) -> tuple[bool, float]:
        passed = target_ok and all(ok for _, ok in checks)
        if not target_ok:
            return False, 0.0
        if not checks:
            return passed, 1.0 if passed else 0.0
        return passed, sum(1 for _, ok in checks if ok) / len(checks)

    async def run_case(
        self,
        case: EvalCase,
        *,
        grants: GrantSet,
        actor: str = "eval",
        context: InvocationContext | None = None,
    ) -> EvalRun:
        case = await self._active_case(case)
        run_id = uuid.uuid4().hex
        if context is not None:
            if context.tenant_id != case.tenant_id:
                raise ValueError("evaluation context tenant does not match its case")
            ctx = replace(context, run_id=run_id)
            grants = context.grants
        else:
            ctx = InvocationContext(
                tenant_id=case.tenant_id,
                grants=grants,
                actor=actor,
                actor_tier="human",
                run_id=run_id,
                extra=dict(case.input or {}),
            )
        result, authority, target_ok, target_detail = await self._execute_target(case, grants, ctx)
        checks = await self._checks(case, run_id, result, authority)
        passed, score = self._verdict(target_ok, checks)
        effective = set(result.get("effective_grants", []))
        detail = {
            "target": {"kind": case.target_kind, "ref": case.target_ref},
            **target_detail,
        }
        detail["checks"] = {name: ok for name, ok in checks}
        detail["effective_grants"] = sorted(effective)

        run = EvalRun(
            id=uuid.uuid4().hex,
            tenant_id=case.tenant_id,
            case_id=case.id,
            passed=passed,
            score=score,
            run_id=run_id,
            detail=detail,
        )
        await self._kernel.store.add_eval_run(run)
        return run
