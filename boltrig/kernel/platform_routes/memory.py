"""Memory (MEM, optional) - scope-filtered + residency (SEC-31)."""

from __future__ import annotations

def register(app, P, K) -> None:
    @app.post("/v1/memory/query")
    async def memory_query(body: dict, k=K, p=P) -> dict:
        from boltrig.identity.rbac import memory_owner_scopes

        scopes = memory_owner_scopes(p.subject, p.role, p.scope)
        items = await k.store.query_memory(p.tenant_id, scopes, kind=body.get("kind"),
                                           limit=int(body.get("limit", 20)))
        return {"items": [{"id": m.id, "owner_scope": m.owner_scope, "kind": m.kind,
                           "content": m.content, "source_ref": m.source_ref} for m in items],
                "scopes": scopes}
