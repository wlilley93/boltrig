"""Author-scoped evaluation fixture and lifecycle routes."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from boltrig.kernel.control_routes import dispatch_control_route

from ._shared import audit_authoring, require_author


async def _set_case_lifecycle(
    k,
    p,
    case_id: str,
    action: str,
    request: Request,
) -> JSONResponse:
    require_author(p)
    output, pending = await dispatch_control_route(
        k, p, f"control.eval_case.{action}", {"id": case_id}, request=request
    )
    if pending is not None:
        return pending
    output = output or {}
    await audit_authoring(
        k,
        p,
        f"eval.case.{action}",
        {"id": case_id, "status": output.get("eval_case_status")},
    )
    return JSONResponse(
        {
            "status": "ok",
            "id": case_id,
            "eval_case_status": output.get("eval_case_status"),
        }
    )


def register_eval_case_routes(app, P, K) -> None:
    @app.get("/v1/eval/cases")
    async def eval_cases(k=K, p=P) -> dict:
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
                    "is_active": case.is_active,
                    "status": "active" if case.is_active else "archived",
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
        await audit_authoring(
            k,
            p,
            "eval.case.upsert",
            {"id": output.get("id"), "target": output.get("target")},
        )
        return JSONResponse({"status": "ok", "id": output.get("id")})

    @app.post("/v1/eval/cases/{case_id}/archive")
    async def archive_case(case_id: str, request: Request, k=K, p=P) -> JSONResponse:
        return await _set_case_lifecycle(k, p, case_id, "archive", request)

    @app.post("/v1/eval/cases/{case_id}/restore")
    async def restore_case(case_id: str, request: Request, k=K, p=P) -> JSONResponse:
        return await _set_case_lifecycle(k, p, case_id, "restore", request)
