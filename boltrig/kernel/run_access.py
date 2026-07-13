"""Visibility checks for run-scoped event streams."""

from __future__ import annotations

from typing import Any, Protocol

from boltrig.identity.rbac import departments_for
from boltrig.models import AuditEvent, WorkItem


class RunEventPrincipal(Protocol):
    tenant_id: str
    role: str
    scope: dict[str, Any]
    active_workspace_id: str | None


class RunEventStore(Protocol):
    async def audit_query(
        self, tenant_id: str, run_id: str | None = None, limit: int = 200
    ) -> list[AuditEvent]: ...

    async def get_work_item_by_run_id(
        self, tenant_id: str, run_id: str
    ) -> WorkItem | None: ...


async def visible_run_events(
    store: RunEventStore,
    principal: RunEventPrincipal,
    run_id: str,
    *,
    audit_limit: int = 1000,
) -> list[AuditEvent] | None:
    """Return run audit rows only when the caller may subscribe to its raw events."""
    rows = await store.audit_query(principal.tenant_id, run_id=run_id, limit=audit_limit)
    if not rows:
        return None

    departments = departments_for(principal.role, principal.scope)
    if departments is not None:
        item = await store.get_work_item_by_run_id(principal.tenant_id, run_id)
        if item is None or item.owner_member not in set(departments):
            return None

    workspace_id = principal.active_workspace_id
    if workspace_id is not None and any(
        row.workspace_id not in (None, workspace_id) for row in rows
    ):
        return None

    return rows
