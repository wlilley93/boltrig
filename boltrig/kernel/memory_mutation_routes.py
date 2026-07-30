"""Governed memory mutation routes."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from boltrig.identity.rbac import memory_owner_scopes
from boltrig.models import PendingHuman
from boltrig.store.base import MAX_INGEST_ITEMS


def memory_scopes(p) -> list[str]:
    return memory_owner_scopes(p.subject, p.role, p.scope)


def memory_context(p):
    return p.context(trusted_extra={"memory_scopes": memory_scopes(p)})


async def _governed_mutation(k, p, verb: str, params: dict, request: Request):
    try:
        return await k.invoke(
            "memory",
            verb,
            params,
            memory_context(p),
            approval_id=request.headers.get("x-boltrig-approval-id"),
        )
    except PendingHuman as exc:
        return JSONResponse(
            {"status": "pending_human", "hitl_request_id": exc.hitl_request_id},
            status_code=202,
        )


def _register_fact_mutation_routes(app, P, K) -> None:
    @app.post("/v1/memory/recall")
    async def recall(body: dict, k=K, p=P) -> JSONResponse:
        params = {
            "query": body.get("query", ""),
            "mode": body.get("mode", "graph_completion"),
            "limit": body.get("limit", 20),
        }
        if body.get("owner_scope") is not None:
            params["owner_scope"] = body["owner_scope"]
        return JSONResponse(await k.invoke("memory", "memory.recall", params, memory_context(p)))

    @app.post("/v1/memory/remember")
    async def remember(body: dict, request: Request, k=K, p=P) -> JSONResponse:
        out = await _governed_mutation(k, p, "memory.remember", body, request)
        if isinstance(out, JSONResponse):
            return out
        return JSONResponse({"status": "ok", **out})

    @app.post("/v1/memory/improve")
    async def improve(body: dict, request: Request, k=K, p=P) -> JSONResponse:
        if body.get("signal") not in {"up", "down"} or not body.get("target"):
            return JSONResponse(
                {
                    "status": "error",
                    "reason": "target and an up/down signal are required",
                },
                status_code=400,
            )
        out = await _governed_mutation(
            k,
            p,
            "memory.improve",
            {"signal": body["signal"], "target": body["target"]},
            request,
        )
        if isinstance(out, JSONResponse):
            return out
        return JSONResponse({"status": "ok", **out})

    @app.post("/v1/memory/forget")
    async def forget(body: dict, request: Request, k=K, p=P) -> JSONResponse:
        params = {key: body[key] for key in ("target", "source_ref") if body.get(key) is not None}
        if not params:
            return JSONResponse(
                {"status": "error", "reason": "target or source_ref is required"},
                status_code=400,
            )
        out = await _governed_mutation(k, p, "memory.forget", params, request)
        if isinstance(out, JSONResponse):
            return out
        return JSONResponse({"status": "ok", **out})


def _register_ingest_route(app, P, K) -> None:
    @app.post("/v1/memory/ingest")
    async def ingest(body: dict, request: Request, k=K, p=P) -> JSONResponse:
        owner_scope = body.get("owner_scope") or f"user:{p.subject}"
        if owner_scope not in set(memory_scopes(p)):
            return JSONResponse(
                {"status": "denied", "reason": f"scope {owner_scope} not permitted"},
                status_code=403,
            )
        items = body.get("items") or []
        if len(items) > MAX_INGEST_ITEMS:
            return JSONResponse(
                {
                    "status": "error",
                    "reason": f"too many items (max {MAX_INGEST_ITEMS})",
                },
                status_code=413,
            )
        out = await _governed_mutation(
            k,
            p,
            "memory.ingest",
            {
                "source_kind": body.get("source_kind", "document"),
                "source_ref": body.get("source_ref", ""),
                "owner_scope": owner_scope,
                "items": [str(item) for item in items],
            },
            request,
        )
        if isinstance(out, JSONResponse):
            return out
        return JSONResponse({"status": "ok", **out})


def register_memory_mutation_routes(app, P, K) -> None:
    _register_fact_mutation_routes(app, P, K)
    _register_ingest_route(app, P, K)
