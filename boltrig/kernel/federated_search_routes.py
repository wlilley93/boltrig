"""Bounded, scope-preserving search across canonical Worker resources."""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Depends
from fastapi.responses import JSONResponse

from boltrig.models import BoltrigError
from boltrig.models.work import work_item_run_id

from .memory_mutation_routes import memory_context
from .platform_routes._shared import scope_depts

SearchHit = dict[str, Any]
SearchResult = tuple[list[SearchHit], bool]
SearchHandler = Callable[[Any, Any, str, int], Awaitable[SearchResult]]

SOURCES = (
    "conversations",
    "executions",
    "knowledge",
    "memory",
    "audit",
)
MAX_TITLE_CHARS = 160
MAX_PREVIEW_CHARS = 240


def _bounded_text(value: Any, maximum: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= maximum:
        return text
    return f"{text[:maximum - 3].rstrip()}..."


def _preview(value: Any) -> str | None:
    preview = _bounded_text(value, MAX_PREVIEW_CHARS)
    return preview or None


def _occurred_at(value: Any) -> str | None:
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else None


def _score(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    score = float(value)
    return score if math.isfinite(score) else None


async def _conversation_results(kernel: Any, principal: Any, query: str, limit: int) -> SearchResult:
    pairs, next_offset = await kernel.store.search_conversations(
        principal.tenant_id,
        principal.subject,
        query,
        limit=limit + 1,
        offset=0,
    )
    selected = pairs[:limit]
    return (
        [
            {
                "source": "conversations",
                "id": conversation.id,
                "title": _bounded_text(conversation.title or "Untitled task", MAX_TITLE_CHARS),
                "preview": _preview(snippet),
                "route": "chat",
                "route_id": conversation.id,
                "occurred_at": _occurred_at(conversation.updated_at),
                "metadata": {"status": conversation.status.value},
            }
            for conversation, snippet in selected
        ],
        len(pairs) > limit or next_offset is not None,
    )


async def _execution_results(kernel: Any, principal: Any, query: str, limit: int) -> SearchResult:
    items = await kernel.store.search_execution_items_scoped(
        principal.tenant_id,
        query,
        departments=scope_depts(principal),
        workspace_id=principal.active_workspace_id,
        limit=limit + 1,
    )
    selected = items[:limit]
    results = []
    for item in selected:
        run_id = work_item_run_id(item)
        results.append({
            "source": "executions",
            "id": run_id,
            "title": _bounded_text(item.intent or run_id, MAX_TITLE_CHARS),
            "preview": _preview(
                " · ".join(
                    value
                    for value in (
                        item.status.value,
                        item.owner_member,
                        item.source,
                    )
                    if value
                )
            ),
            "route": "runs",
            "route_id": run_id,
            "metadata": {
                "work_item_id": item.id,
                "status": item.status.value,
                "owner": item.owner_member,
                "on_behalf_of": item.on_behalf_of,
                "source": item.source,
                "external_ref": item.source_id,
            },
        })
    return results, len(items) > limit


async def _knowledge_results(kernel: Any, principal: Any, query: str, limit: int) -> SearchResult:
    output = await kernel.invoke(
        "knowledge",
        "knowledge.search",
        {"query": query, "limit": limit + 1},
        principal.context(),
    )
    hits = list(output.get("hits") or [])
    results = []
    for hit in hits[:limit]:
        score = _score(hit.get("score"))
        row: SearchHit = {
            "source": "knowledge",
            "id": str(hit.get("segment_id") or hit.get("asset_id") or ""),
            "title": _bounded_text(hit.get("title") or hit.get("filename") or "Knowledge", MAX_TITLE_CHARS),
            "preview": _preview(hit.get("text")),
            "route": "knowledge",
            "route_id": str(hit.get("asset_id") or "") or None,
            "metadata": {
                "asset_id": hit.get("asset_id"),
                "revision_id": hit.get("revision_id"),
                "segment_id": hit.get("segment_id"),
                "filename": hit.get("filename"),
                "citation": hit.get("citation"),
            },
        }
        if score is not None:
            row["score"] = score
        results.append(row)
    return results, len(hits) > limit


async def _memory_results(kernel: Any, principal: Any, query: str, limit: int) -> SearchResult:
    output = await kernel.invoke(
        "memory",
        "memory.recall",
        {"query": query, "mode": "graph_completion", "limit": limit + 1},
        memory_context(principal),
    )
    facts = list(output.get("facts") or [])
    return (
        [
            {
                "source": "memory",
                "id": str(fact.get("id") or ""),
                "title": _bounded_text(
                    f"{str(fact.get('kind') or 'Memory').replace('_', ' ')} memory",
                    MAX_TITLE_CHARS,
                ),
                "preview": _preview(fact.get("content")),
                "route": "memory",
                # The exact destination re-authorizes tenant + owner scope.
                "route_id": str(fact.get("id") or ""),
                "metadata": {
                    "owner_scope": fact.get("owner_scope"),
                    "kind": fact.get("kind"),
                    "data_class": fact.get("data_class"),
                    "provenance": fact.get("provenance"),
                    "projection": fact.get("projection"),
                },
            }
            for fact in facts[:limit]
        ],
        len(facts) > limit,
    )


async def _audit_results(kernel: Any, principal: Any, query: str, limit: int) -> SearchResult:
    events, next_offset = await kernel.store.audit_search_page(
        principal.tenant_id,
        departments=scope_depts(principal),
        workspace_id=principal.active_workspace_id,
        query=query,
        limit=limit + 1,
        offset=0,
    )
    selected = events[:limit]
    return (
        [
            {
                "source": "audit",
                "id": str(event.seq),
                "title": _bounded_text(
                    event.verb or event.action_type.value,
                    MAX_TITLE_CHARS,
                ),
                "preview": _preview(
                    " · ".join(
                        value for value in (event.actor, event.status) if value
                    )
                ),
                "route": "operate",
                "route_id": None,
                "occurred_at": _occurred_at(event.ts),
                "metadata": {
                    "actor": event.actor,
                    "status": event.status,
                    "run_id": event.run_id,
                    "resource": event.resource,
                    "resource_id": event.resource_id,
                    "workspace_id": event.workspace_id,
                },
            }
            for event in selected
        ],
        len(events) > limit or next_offset is not None,
    )


HANDLERS: dict[str, SearchHandler] = {
    "conversations": _conversation_results,
    "executions": _execution_results,
    "knowledge": _knowledge_results,
    "memory": _memory_results,
    "audit": _audit_results,
}


def _request_values(body: dict[str, Any]) -> tuple[str, int, list[str]] | JSONResponse:
    raw_query = body.get("query")
    query = raw_query.strip() if isinstance(raw_query, str) else ""
    if not query or len(query) > 200:
        return JSONResponse(
            {"status": "error", "reason": "query must contain 1..200 characters"},
            status_code=400,
        )

    raw_limit = body.get("limit", 5)
    if isinstance(raw_limit, bool) or not isinstance(raw_limit, int) or not 1 <= raw_limit <= 10:
        return JSONResponse(
            {"status": "error", "reason": "limit must be an integer from 1 to 10"},
            status_code=400,
        )

    raw_sources = body.get("sources")
    if raw_sources is None:
        sources = list(SOURCES)
    elif not isinstance(raw_sources, list) or any(
        not isinstance(source, str) or source not in SOURCES
        for source in raw_sources
    ):
        return JSONResponse(
            {"status": "error", "reason": "sources contains an unsupported source"},
            status_code=400,
        )
    else:
        sources = list(dict.fromkeys(raw_sources))
    return query, raw_limit, sources


def register_federated_search_routes(app, principal_dep, get_kernel) -> None:
    P = Depends(principal_dep)
    K = Depends(get_kernel)

    @app.post("/v1/search")
    async def federated_search(body: dict[str, Any], k=K, p=P):
        values = _request_values(body)
        if isinstance(values, JSONResponse):
            return values
        query, limit, requested_sources = values
        results: list[SearchHit] = []
        summaries = []
        for source in requested_sources:
            try:
                source_results, truncated = await HANDLERS[source](k, p, query, limit)
            except BoltrigError as exc:
                status = "denied" if exc.status_code == 403 else "unavailable"
                summaries.append({
                    "source": source,
                    "status": status,
                    "count": 0,
                    "truncated": False,
                    "reason": exc.reason,
                })
                continue
            results.extend(source_results)
            summaries.append({
                "source": source,
                "status": "ok",
                "count": len(source_results),
                "truncated": truncated,
            })
        return {
            "query": query,
            "limit": limit,
            "results": results,
            "sources": summaries,
        }


__all__ = ["register_federated_search_routes"]
