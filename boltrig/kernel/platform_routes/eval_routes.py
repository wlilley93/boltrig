"""Evaluation (EVAL): cases, run, runs."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
import uuid
from boltrig.models import EvalCase
from ._shared import platform_state, require_author


def register(app, P, K) -> None:
    @app.post("/v1/eval/cases")
    async def create_case(body: dict, k=K, p=P) -> JSONResponse:
        require_author(p)
        case = EvalCase(id=body.get("id") or uuid.uuid4().hex, tenant_id=p.tenant_id,
                        target_kind=body["target_kind"], target_ref=body["target_ref"],
                        input=body.get("input", {}), assertions=body.get("assertions", {}),
                        labels=body.get("labels", []))
        await k.store.upsert_eval_case(case)
        return JSONResponse({"status": "ok", "id": case.id})

    @app.post("/v1/eval/run")
    async def run_eval(body: dict, request: Request, k=K, p=P) -> JSONResponse:
        runner = platform_state(request).get("eval")
        if runner is None:
            return JSONResponse({"error": "eval_unavailable"}, status_code=503)
        case = await k.store.get_eval_case(p.tenant_id, body["case_id"])
        if case is None:
            return JSONResponse({"error": "no_such_case"}, status_code=404)
        run = await runner.run_case(case, grants=p.grants, actor=p.subject)  # under caller grants
        return JSONResponse({"id": run.id, "passed": run.passed, "score": run.score,
                             "run_id": run.run_id, "detail": run.detail})

    @app.get("/v1/eval/runs")
    async def eval_runs(case_id: str | None = None, k=K, p=P) -> dict:
        runs = await k.store.list_eval_runs(p.tenant_id, case_id)
        return {"runs": [{"id": r.id, "case_id": r.case_id, "passed": r.passed,
                          "score": r.score, "run_id": r.run_id} for r in runs]}
