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


def _register_core_read_routes(app, *, P, K, scopes) -> None:
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

    @app.get("/v1/memory/candidates")
    async def list_candidates(limit: int = 50, k=K, p=P) -> dict:
        rows = await k.store.list_memory_candidates(
            p.tenant_id, scopes(p), limit=clamp_memory_list(limit)
        )
        return {
            "candidates": [
                {
                    **_fact_view(fact),
                    "memory_key": fact.memory_key,
                    "status": fact.status,
                    "version": fact.version,
                    "confidence": fact.confidence,
                }
                for fact in rows
            ]
        }

    @app.get("/v1/memory/resolve")
    async def resolve(
        subject_type: str,
        subject_id: str,
        predicates: str | None = None,
        k=K,
        p=P,
    ):
        from boltrig.kernel.memory_mutation_routes import memory_context

        params = {"subject_type": subject_type, "subject_id": subject_id}
        if predicates:
            params["predicates"] = [part for part in predicates.split(",") if part]
        return dict(await k.invoke("memory", "memory.resolve", params, memory_context(p)))


def _register_slot_timeline_route(app, *, P, K, scopes) -> None:
    @app.get("/v1/memory/timeline")
    async def slot_timeline(
        subject_type: str | None = None,
        subject_id: str | None = None,
        predicate: str | None = None,
        owner_scope: str | None = None,
        memory_key: str | None = None,
        limit: int = 50,
        k=K,
        p=P,
    ):
        from boltrig.memory.typology import semantic_memory_key

        permitted = scopes(p)
        allowed = set(permitted)
        if memory_key:
            # A direct slot key (the candidate queue's shape): the versions
            # filter below is the scope guard; the key only narrows the query.
            key = memory_key
        else:
            if not (subject_type and subject_id and predicate):
                return JSONResponse(
                    {"error": "subject_type, subject_id and predicate are required"},
                    status_code=400,
                )
            # Default to the caller's own scope (the `memory_owner_scopes` head).
            scope = owner_scope or permitted[0]
            if scope not in allowed:
                return JSONResponse({"error": "not_found"}, status_code=404)
            key = semantic_memory_key(subject_type, subject_id, predicate, scope)
        rows = await k.store.list_memory_slot_history(
            p.tenant_id, key, limit=clamp_memory_list(limit)
        )
        versions = [fact for fact in rows if fact.owner_scope in allowed]
        return {
            "memory_key": key,
            "versions": [
                {
                    **_fact_view(fact),
                    "status": fact.status,
                    "version": fact.version,
                    "value": (fact.payload or {}).get("value"),
                    "confidence": fact.confidence,
                    "valid_from": fact.valid_from.isoformat() if fact.valid_from else None,
                    "valid_to": fact.valid_to.isoformat() if fact.valid_to else None,
                    "supersedes_id": fact.supersedes_id,
                }
                for fact in versions
            ],
        }


def register_memory_read_routes(app, *, P, K, scopes) -> None:
    _register_core_read_routes(app, P=P, K=K, scopes=scopes)
    _register_slot_timeline_route(app, P=P, K=K, scopes=scopes)
