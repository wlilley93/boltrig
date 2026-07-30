"""Governed author controls for the canonical Work board."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from boltrig.kernel.control_routes import dispatch_control_route

from ._shared import require_author


async def _dispatch(
    verb: str,
    params: dict[str, Any],
    request: Request,
    kernel: Any,
    principal: Any,
) -> JSONResponse:
    require_author(principal)
    output, pending = await dispatch_control_route(
        kernel, principal, verb, params, request=request
    )
    if pending is not None:
        return pending
    return JSONResponse({"status": "ok", **(output or {})})


def register(app: Any, P: Any, K: Any) -> None:
    @app.post("/v1/work")
    async def create_work(
        body: dict[str, Any], request: Request, k=K, p=P
    ) -> JSONResponse:
        return await _dispatch("control.work.create", body, request, k, p)

    @app.patch("/v1/work/{item_id}/assignment")
    async def assign_work(
        item_id: str, body: dict[str, Any], request: Request, k=K, p=P
    ) -> JSONResponse:
        return await _dispatch(
            "control.work.assign", {**body, "item_id": item_id}, request, k, p
        )

    @app.patch("/v1/work/{item_id}/status")
    async def transition_work(
        item_id: str, body: dict[str, Any], request: Request, k=K, p=P
    ) -> JSONResponse:
        return await _dispatch(
            "control.work.status", {**body, "item_id": item_id}, request, k, p
        )

    @app.patch("/v1/work/{item_id}/parent")
    async def reparent_work(
        item_id: str, body: dict[str, Any], request: Request, k=K, p=P
    ) -> JSONResponse:
        return await _dispatch(
            "control.work.reparent", {**body, "item_id": item_id}, request, k, p
        )
