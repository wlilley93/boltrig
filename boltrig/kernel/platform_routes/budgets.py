"""Budget read, policy, and usage-reset HTTP routes."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from boltrig.kernel.control_routes import dispatch_control_route

from ._shared import require_author, scope_depts


def _row(budget):
    return {
        "id": budget.id,
        "scope_type": budget.scope_type,
        "window": budget.window,
        "hard_stop": budget.hard_stop,
        "token_limit": budget.token_limit,
        "spent_tokens": budget.spent_tokens,
        "cost_limit_micros": budget.cost_limit_micros,
        "spent_micros": budget.spent_micros,
    }


def register(app, P, K) -> None:
    @app.get("/v1/budgets")
    async def list_budgets(k=K, p=P) -> dict:
        depts = scope_depts(p)
        rows = [
            _row(budget)
            for budget in await k.store.list_budgets(p.tenant_id)
            if not (
                budget.scope_type == "department"
                and depts is not None
                and budget.id not in depts
            )
        ]
        return {"budgets": rows, "scope": depts or "all"}

    @app.put("/v1/budgets/{scope_type}/{scope_id}")
    async def upsert_budget(
        scope_type: str, scope_id: str, body: dict, request: Request, k=K, p=P
    ) -> JSONResponse:
        require_author(p)
        output, pending = await dispatch_control_route(
            k, p, "control.budget.upsert",
            {"scope_type": scope_type, "scope_id": scope_id, **body},
            request=request,
        )
        return pending or JSONResponse({"status": "ok", **(output or {})})

    @app.post("/v1/budgets/{scope_type}/{scope_id}/reset")
    async def reset_budget(
        scope_type: str, scope_id: str, body: dict, request: Request, k=K, p=P
    ) -> JSONResponse:
        require_author(p)
        output, pending = await dispatch_control_route(
            k, p, "control.budget.reset",
            {"scope_type": scope_type, "scope_id": scope_id, **body},
            request=request,
        )
        return pending or JSONResponse({"status": "ok", **(output or {})})
