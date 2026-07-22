"""Round Five HTTP surface: the memory verbs + scoped reads (Epic MEM/RCL/LRN/MUI).

recall / remember / forget / ingest run through the kernel chokepoint by invoking
the ``memory.*`` verbs - so grant check + audit apply and the MemoryAdapter
enforces owner-scope (SEC-40). The caller's permitted owner-scopes are computed
from the Principal (rbac.memory_owner_scopes) and carried in the invocation
context, so the kernel - not the engine - is the boundary. The facts/ingestions
reads are scope-filtered (C5). These are also drivable headless / via MCP since a
PAT or bearer yields the same Principal (Round Four HEAD).
"""

from __future__ import annotations

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from boltrig.store.base import MAX_INGEST_ITEMS, clamp_memory_list




def register_memory_routes(app, *, principal_dep, get_kernel) -> None:
    P = Depends(principal_dep)
    K = Depends(get_kernel)

    def _scopes(p) -> list[str]:
        from boltrig.identity.rbac import memory_owner_scopes

        return memory_owner_scopes(p.subject, p.role, p.scope)

    def _ctx(p):
        # Server-derived owner scopes are kernel-trusted: they ride the trusted
        # stamping channel so the caller-body denylist in Principal.context can
        # never strip (or spoof) them.
        return p.context(trusted_extra={"memory_scopes": _scopes(p)})

    @app.post("/v1/memory/recall")
    async def recall(body: dict, k=K, p=P) -> JSONResponse:
        out = await k.invoke("memory", "memory.recall", {
            "query": body.get("query", ""), "mode": body.get("mode", "graph_completion"),
            "limit": body.get("limit", 20),
        }, _ctx(p))
        return JSONResponse(out)

    @app.post("/v1/memory/remember")
    async def remember(body: dict, k=K, p=P) -> JSONResponse:
        out = await k.invoke("memory", "memory.remember", body, _ctx(p))
        return JSONResponse({"status": "ok", **out})

    @app.post("/v1/memory/forget")
    async def forget(body: dict, k=K, p=P) -> JSONResponse:
        # omit unset fields so they do not fail the verb's string schema (a null
        # is not a string).
        params = {key: body[key] for key in ("target", "source_ref")
                  if body.get(key) is not None}
        if not params:
            return JSONResponse(
                {"status": "error", "reason": "target or source_ref is required"},
                status_code=400,
            )
        out = await k.invoke("memory", "memory.forget", params, _ctx(p))
        return JSONResponse({"status": "ok", **out})

    @app.post("/v1/memory/ingest")
    async def ingest(body: dict, request: Request, k=K, p=P) -> JSONResponse:
        from boltrig.memory.cognify import cognify, cognify_conversation

        owner_scope = body.get("owner_scope") or f"user:{p.subject}"
        if owner_scope not in set(_scopes(p)):
            return JSONResponse({"status": "denied", "reason": f"scope {owner_scope} not permitted"},
                                status_code=403)
        # M9-memory / SEC-009 / SEC-69: cap the batch item count so one ingest
        # request cannot enqueue an unbounded amount of screening work.
        items = body.get("items") or []
        if len(items) > MAX_INGEST_ITEMS:
            return JSONResponse(
                {"status": "error", "reason": f"too many items (max {MAX_INGEST_ITEMS})"},
                status_code=413,
            )
        executor = (getattr(request.app.state, "platform", {}) or {}).get("workflow_executor")
        if body.get("source_kind") == "conversation" and body.get("source_ref"):
            ing = await cognify_conversation(
                k, p.tenant_id, body["source_ref"], owner_scope=owner_scope,
                context=_ctx(p), executor=executor)
        else:
            ing = await cognify(
                k, p.tenant_id, source_kind=body.get("source_kind", "document"),
                source_ref=body.get("source_ref", ""), owner_scope=owner_scope,
                items=[str(x) for x in (body.get("items") or [])], context=_ctx(p),
                executor=executor)
        return JSONResponse({"status": "ok", "id": ing.id, "ingestion_status": ing.status,
                             "facts_added": ing.facts_added, "screened": ing.screened})

    @app.get("/v1/memory/facts")
    async def list_facts(kind: str | None = None, limit: int = 50, k=K, p=P) -> dict:
        # M9-memory / SEC-009 / SEC-69: clamp the caller-supplied page size.
        limit = clamp_memory_list(limit)
        facts = await k.store.list_memory_facts(p.tenant_id, _scopes(p), kind=kind, limit=limit)
        return {"facts": [
            {"id": f.id, "owner_scope": f.owner_scope, "kind": f.kind, "content": f.content,
             "data_class": f.data_class,
             "provenance": {"source_kind": f.source_kind, "source_ref": f.source_ref,
                            "created_at": f.created_at.isoformat() if f.created_at else None}}
            for f in facts
        ], "scopes": _scopes(p)}

    @app.get("/v1/memory/ingestions")
    async def list_ingestions(limit: int = 50, k=K, p=P) -> dict:
        # M9-memory / SEC-009 / SEC-69: clamp the caller-supplied page size.
        limit = clamp_memory_list(limit)
        rows = await k.store.list_memory_ingestions(p.tenant_id, limit=limit)
        permitted = set(_scopes(p))
        is_admin = p.role == "org-admin"
        return {"ingestions": [
            {"id": i.id, "source_kind": i.source_kind, "source_ref": i.source_ref,
             "owner_scope": i.owner_scope, "status": i.status, "facts_added": i.facts_added,
             "screened": i.screened,
             "created_at": i.created_at.isoformat() if i.created_at else None}
            for i in rows if is_admin or i.owner_scope in permitted
        ]}
