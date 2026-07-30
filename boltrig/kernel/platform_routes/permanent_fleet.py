"""Permanent-fleet desired/observed author surface."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from boltrig.config.permanent_fleet import permanent_fleet_view
from boltrig.kernel.control_routes import dispatch_control_route

from ._shared import require_author


def register(app, P, K) -> None:
    @app.get("/v1/permanent-fleet")
    async def get_permanent_fleet(k=K, p=P) -> dict[str, Any]:
        require_author(p)
        return await permanent_fleet_view(k.store, p.tenant_id)

    @app.put("/v1/permanent-fleet")
    async def apply_permanent_fleet(
        body: dict, request: Request, k=K, p=P
    ) -> JSONResponse:
        require_author(p)
        output, pending = await dispatch_control_route(
            k,
            p,
            "control.permanent_fleet.apply",
            {
                "hierarchy": body.get("hierarchy"),
                "approval_id": body.get("approval_id"),
            },
            request=request,
        )
        if pending is not None:
            return pending
        return JSONResponse({"status": "ok", **(output or {})})
