"""Evaluation (EVAL): cases, run, runs."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from boltrig.models import EVAL_TARGET_KINDS

from ._shared import audit_authoring, platform_state, require_author
from .eval_case_routes import register_eval_case_routes


def _target_view(run: Any) -> dict[str, str]:
    detail = run.detail if isinstance(run.detail, dict) else {}
    target = detail.get("target")
    if not isinstance(target, dict):
        return {}
    kind = target.get("kind")
    ref = target.get("ref")
    if kind not in EVAL_TARGET_KINDS or not isinstance(ref, str):
        return {}
    return {"target_kind": kind, "target_ref": ref}


def register(app, P, K) -> None:
    register_eval_case_routes(app, P, K)

    @app.post("/v1/eval/run")
    async def run_eval(body: dict, request: Request, k=K, p=P) -> JSONResponse:
        # Drives model spend, so it sits on the same author/admin boundary as case
        # creation; a missing case_id is a client error, never a 500.
        require_author(p)
        case_id = body.get("case_id")
        if not case_id:
            return JSONResponse(
                {"status": "error", "reason": "case_id is required"}, status_code=400
            )
        runner = platform_state(request).get("eval")
        if runner is None:
            return JSONResponse({"error": "eval_unavailable"}, status_code=503)
        case = await k.store.get_eval_case(p.tenant_id, case_id)
        if case is None:
            return JSONResponse({"error": "no_such_case"}, status_code=404)
        if not case.is_active:
            return JSONResponse({"error": "eval_case_archived"}, status_code=409)
        run = await runner.run_case(
            case,
            grants=p.grants,
            actor=p.subject,
            context=p.context(extra=case.input),
        )
        # The eval's sub-verbs are audited at the chokepoint; also record the run
        # initiation itself (who ran which case, and the verdict) as one authoring row.
        await audit_authoring(
            k,
            p,
            "eval.run",
            {
                "case_id": case_id,
                "run_id": run.run_id,
                "passed": run.passed,
                "target_kind": case.target_kind,
                "target_ref": case.target_ref,
            },
        )
        return JSONResponse(
            {
                "id": run.id,
                "passed": run.passed,
                "score": run.score,
                "run_id": run.run_id,
                "detail": run.detail,
                **_target_view(run),
            }
        )

    @app.get("/v1/eval/runs")
    async def eval_runs(case_id: str | None = None, k=K, p=P) -> dict:
        require_author(p)
        runs = await k.store.list_eval_runs(p.tenant_id, case_id)
        return {
            "runs": [
                {
                    "id": r.id,
                    "case_id": r.case_id,
                    "passed": r.passed,
                    "score": r.score,
                    "run_id": r.run_id,
                    "detail": r.detail,
                    "created_at": r.created_at.isoformat(),
                    **_target_view(r),
                }
                for r in runs
            ]
        }
