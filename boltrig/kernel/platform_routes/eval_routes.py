"""Evaluation (EVAL): cases, run, runs."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from boltrig.kernel.control_routes import dispatch_control_route

from ._shared import audit_authoring, platform_state, require_author


def register(app, P, K) -> None:
    @app.get("/v1/eval/cases")
    async def eval_cases(k=K, p=P) -> dict:
        # Eval inputs and assertions can contain sensitive test fixtures. Keep the
        # catalogue on the same author/admin boundary as case creation, and always
        # query through the caller's tenant-bound store context.
        require_author(p)
        cases = sorted(await k.store.list_eval_cases(p.tenant_id), key=lambda case: case.id)
        return {
            "cases": [
                {
                    "id": case.id,
                    "target_kind": case.target_kind,
                    "target_ref": case.target_ref,
                    "input": case.input,
                    "assertions": case.assertions,
                    "labels": case.labels,
                }
                for case in cases
            ]
        }

    @app.post("/v1/eval/cases")
    async def create_case(body: dict, request: Request, k=K, p=P) -> JSONResponse:
        require_author(p)
        output, pending = await dispatch_control_route(
            k, p, "control.eval_case.upsert", body, request=request
        )
        if pending is not None:
            return pending
        output = output or {}
        # Audit the authoring mutation like every sibling authoring route (eval cases
        # gate workflow promotion, so creating/editing one is governance-relevant).
        await audit_authoring(
            k, p, "eval.case.upsert", {"id": output.get("id"), "target": output.get("target")}
        )
        return JSONResponse({"status": "ok", "id": output.get("id")})

    @app.post("/v1/eval/run")
    async def run_eval(body: dict, request: Request, k=K, p=P) -> JSONResponse:
        # Drives model spend, so it sits on the same author/admin boundary as case
        # creation; a missing case_id is a client error, never a 500.
        require_author(p)
        case_id = body.get("case_id")
        if not case_id:
            return JSONResponse({"status": "error", "reason": "case_id is required"},
                                status_code=400)
        runner = platform_state(request).get("eval")
        if runner is None:
            return JSONResponse({"error": "eval_unavailable"}, status_code=503)
        case = await k.store.get_eval_case(p.tenant_id, case_id)
        if case is None:
            return JSONResponse({"error": "no_such_case"}, status_code=404)
        run = await runner.run_case(case, grants=p.grants, actor=p.subject)  # under caller grants
        # The eval's sub-verbs are audited at the chokepoint; also record the run
        # initiation itself (who ran which case, and the verdict) as one authoring row.
        await audit_authoring(
            k,
            p,
            "eval.run",
            {"case_id": case_id, "run_id": run.run_id, "passed": run.passed},
        )
        return JSONResponse(
            {
                "id": run.id,
                "passed": run.passed,
                "score": run.score,
                "run_id": run.run_id,
                "detail": run.detail,
            }
        )

    @app.get("/v1/eval/runs")
    async def eval_runs(case_id: str | None = None, k=K, p=P) -> dict:
        runs = await k.store.list_eval_runs(p.tenant_id, case_id)
        return {
            "runs": [
                {
                    "id": r.id,
                    "case_id": r.case_id,
                    "passed": r.passed,
                    "score": r.score,
                    "run_id": r.run_id,
                }
                for r in runs
            ]
        }
