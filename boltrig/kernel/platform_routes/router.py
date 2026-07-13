"""Router authoring (RTR): nouns, verbs, bindings."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from boltrig.kernel.control_routes import dispatch_control_route
from ._shared import require_author


def register(app, P, K) -> None:
    @app.post("/v1/nouns")
    async def upsert_noun(body: dict, request: Request, k=K, p=P) -> JSONResponse:
        require_author(p)
        output, pending = await dispatch_control_route(
            k, p, "control.noun.define", body, request=request
        )
        if pending is not None:
            return pending
        return JSONResponse({"status": "ok", **(output or {})})

    @app.post("/v1/verbs")
    async def upsert_verb(body: dict, request: Request, k=K, p=P) -> JSONResponse:
        require_author(p)
        output, pending = await dispatch_control_route(
            k, p, "control.verb.define", body, request=request
        )
        if pending is not None:
            return pending
        return JSONResponse({"status": "ok", **(output or {})})

    @app.post("/v1/verbs/{verb_id}/binding")
    async def set_binding(
        verb_id: str, body: dict, request: Request, k=K, p=P
    ) -> JSONResponse:
        require_author(p)
        output, pending = await dispatch_control_route(
            k,
            p,
            "control.binding.set",
            {"verb_id": verb_id, **body},
            request=request,
        )
        if pending is not None:
            return pending
        return JSONResponse({"status": "ok", **(output or {})})
