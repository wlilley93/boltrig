"""Bounded, principal-scoped memory read projections."""

from __future__ import annotations

from fastapi.responses import JSONResponse

from boltrig.store.base import clamp_memory_list


def _fact_view(fact) -> dict:
    return {
        "id": fact.id,
        "owner_scope": fact.owner_scope,
        "kind": fact.kind,
        "content": fact.content,
        "data_class": fact.data_class,
        "provenance": {
            "source_kind": fact.source_kind,
            "source_ref": fact.source_ref,
            "created_at": (
                fact.created_at.isoformat() if fact.created_at else None
            ),
        },
    }


def register_memory_read_routes(app, *, P, K, scopes) -> None:
    @app.get("/v1/memory/facts")
    async def list_facts(
        kind: str | None = None, limit: int = 50, k=K, p=P
    ) -> dict:
        limit = clamp_memory_list(limit)
        facts = await k.store.list_memory_facts(
            p.tenant_id, scopes(p), kind=kind, limit=limit
        )
        return {
            "facts": [_fact_view(fact) for fact in facts],
            "scopes": scopes(p),
        }

    @app.get("/v1/memory/facts/{fact_id}")
    async def get_fact(fact_id: str, k=K, p=P):
        fact = await k.store.get_memory_fact(p.tenant_id, fact_id)
        if fact is None or fact.owner_scope not in set(scopes(p)):
            # Hidden and missing are intentionally indistinguishable.
            return JSONResponse({"error": "not_found"}, status_code=404)
        return {"fact": _fact_view(fact)}

    @app.get("/v1/memory/ingestions")
    async def list_ingestions(limit: int = 50, k=K, p=P) -> dict:
        rows = await k.store.list_memory_ingestions(
            p.tenant_id, limit=clamp_memory_list(limit)
        )
        permitted = set(scopes(p))
        return {
            "ingestions": [
                {
                    "id": item.id,
                    "source_kind": item.source_kind,
                    "source_ref": item.source_ref,
                    "owner_scope": item.owner_scope,
                    "status": item.status,
                    "facts_added": item.facts_added,
                    "screened": item.screened,
                    "created_at": (
                        item.created_at.isoformat() if item.created_at else None
                    ),
                }
                for item in rows
                if p.role == "org-admin" or item.owner_scope in permitted
            ]
        }
