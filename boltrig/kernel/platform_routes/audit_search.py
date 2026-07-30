"""Bounded, scope-filtered audit and security-stream search."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import Query, Request
from fastapi.responses import JSONResponse

from boltrig.kernel.schema_diagnosis import diagnose
from boltrig.store.audit_read_contract import (
    DEFAULT_AUDIT_SEARCH_PAGE,
    MAX_AUDIT_SEARCH_OFFSET,
    MAX_AUDIT_SEARCH_PAGE,
)

from ._shared import can_author_route, scope_depts


def _parse_bound(raw: str | None, *, end_of_day: bool) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if end_of_day and len(raw) == 10:
        dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


async def _attach_schema_diagnosis(
    store: Any,
    tenant_id: str,
    pairs: list[tuple[dict, Any]],
) -> None:
    """Render schema failures only against the still-matching current schema."""

    for verb_id in {event.verb for _, event in pairs if event.verb}:
        verb = await store.get_verb_any(tenant_id, verb_id)
        schema = getattr(verb, "input_schema", None) if verb else None
        for row, event in pairs:
            if event.verb == verb_id:
                row["schema_diagnosis"] = diagnose(
                    getattr(event, "detail", None),
                    schema,
                )


def _security_rows(events: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "seq": event.seq,
            "ts": event.ts.isoformat(),
            "actor": event.actor,
            "event_type": event.event_type.value,
            "reason": event.reason,
            "workspace_id": event.workspace_id,
            "ip_address": event.ip_address,
            "user_agent": event.user_agent,
            "resource": event.resource,
            "resource_id": event.resource_id,
        }
        for event in events
    ]


def _audit_rows(events: list[Any]) -> tuple[list[dict[str, Any]], list[tuple[dict, Any]]]:
    rows = []
    schemas = []
    for event in events:
        row = {
            "seq": event.seq,
            "ts": event.ts.isoformat(),
            "actor": event.actor,
            "verb": event.verb,
            "status": event.status,
            "run_id": event.run_id,
            "workspace_id": event.workspace_id,
            "ip_address": event.ip_address,
            "user_agent": event.user_agent,
            "resource": event.resource,
            "resource_id": event.resource_id,
        }
        if event.status == "schema_invalid":
            schemas.append((row, event))
        rows.append(row)
    return rows, schemas


def register(app, P, K) -> None:
    @app.get("/v1/audit/search")
    async def audit_search(
        request: Request,
        actor: str | None = None,
        verb: str | None = None,
        run: str | None = None,
        resource: str | None = None,
        status: str | None = None,
        query: str | None = Query(None, min_length=1, max_length=256),
        since: str | None = None,
        until: str | None = None,
        security: int = 0,
        event_type: str | None = None,
        limit: int = Query(DEFAULT_AUDIT_SEARCH_PAGE, ge=1, le=MAX_AUDIT_SEARCH_PAGE),
        offset: int = Query(0, ge=0, le=MAX_AUDIT_SEARCH_OFFSET),
        k=K,
        p=P,
    ) -> dict:
        depts = scope_depts(p)
        bounds = {
            "since": _parse_bound(since, end_of_day=False),
            "until": _parse_bound(until, end_of_day=True),
        }
        if security:
            if not can_author_route(p):
                return JSONResponse(
                    {"status": "denied", "reason": "author_or_admin_required"},
                    status_code=403,
                )
            events, next_offset = await k.store.security_search_page(
                p.tenant_id,
                workspace_id=p.active_workspace_id,
                event_type=event_type,
                actor=actor,
                resource=resource,
                limit=limit,
                offset=offset,
                **bounds,
            )
            rows = _security_rows(events)
            stream = "security"
        else:
            events, next_offset = await k.store.audit_search_page(
                p.tenant_id,
                departments=depts,
                workspace_id=p.active_workspace_id,
                run_id=run,
                query=query,
                actor=actor,
                verb=verb,
                status=status,
                resource=resource,
                limit=limit,
                offset=offset,
                **bounds,
            )
            rows, schemas = _audit_rows(events)
            await _attach_schema_diagnosis(k.store, p.tenant_id, schemas)
            stream = "audit"
        return {
            "stream": stream,
            "results": rows,
            "scope": depts or "all",
            "limit": limit,
            "offset": offset,
            "next_offset": next_offset,
        }


__all__ = ["register"]
