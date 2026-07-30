"""Governed noun, verb, binding, and lifecycle routes."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from boltrig.kernel.control_routes import dispatch_control_route

from ._shared import require_author


async def _lifecycle(kind, definition_id, action, request, kernel, principal):
    require_author(principal)
    output, pending = await dispatch_control_route(
        kernel,
        principal,
        f"control.{kind}.{action}",
        {"id": definition_id},
        request=request,
    )
    return pending or JSONResponse({"status": "ok", **(output or {})})


def _register_noun_routes(app, P, K) -> None:
    @app.post("/v1/nouns")
    async def upsert_noun(
        body: dict, request: Request, k=K, p=P
    ) -> JSONResponse:
        require_author(p)
        output, pending = await dispatch_control_route(
            k, p, "control.noun.define", body, request=request
        )
        return pending or JSONResponse({"status": "ok", **(output or {})})

    @app.post("/v1/nouns/{noun_id}/archive")
    async def archive_noun(
        noun_id: str, request: Request, k=K, p=P
    ) -> JSONResponse:
        return await _lifecycle("noun", noun_id, "archive", request, k, p)

    @app.post("/v1/nouns/{noun_id}/restore")
    async def restore_noun(
        noun_id: str, request: Request, k=K, p=P
    ) -> JSONResponse:
        return await _lifecycle("noun", noun_id, "restore", request, k, p)


def _register_verb_routes(app, P, K) -> None:
    @app.post("/v1/verbs")
    async def upsert_verb(
        body: dict, request: Request, k=K, p=P
    ) -> JSONResponse:
        require_author(p)
        output, pending = await dispatch_control_route(
            k, p, "control.verb.define", body, request=request
        )
        return pending or JSONResponse({"status": "ok", **(output or {})})

    @app.post("/v1/verbs/{verb_id}/archive")
    async def archive_verb(
        verb_id: str, request: Request, k=K, p=P
    ) -> JSONResponse:
        return await _lifecycle("verb", verb_id, "archive", request, k, p)

    @app.post("/v1/verbs/{verb_id}/restore")
    async def restore_verb(
        verb_id: str, request: Request, k=K, p=P
    ) -> JSONResponse:
        return await _lifecycle("verb", verb_id, "restore", request, k, p)

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
        return pending or JSONResponse({"status": "ok", **(output or {})})


def register_authored_registry_write_routes(app, P, K) -> None:
    _register_noun_routes(app, P, K)
    _register_verb_routes(app, P, K)
