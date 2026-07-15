"""Visibility checks for run-scoped event streams."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Protocol

from boltrig.identity.rbac import departments_for
from boltrig.models import AuditEvent, WorkItem
from boltrig.models.work import work_item_run_id


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
        self,
        tenant_id: str,
        run_id: str,
        workspace_id: str | None = None,
        enforce_workspace: bool = False,
    ) -> WorkItem | None: ...

    async def list_work_items(
        self,
        tenant_id: str,
        status: Any = None,
        parent_id: str | None = None,
        departments: list[str] | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        workspace_id: str | None = None,
        enforce_workspace: bool = False,
    ) -> list[WorkItem]: ...


def _workspace_visible(principal: RunEventPrincipal, row: AuditEvent) -> bool:
    active = principal.active_workspace_id
    return row.workspace_id is None or row.workspace_id == active


async def visible_work_item_by_run(
    store: RunEventStore, principal: RunEventPrincipal, run_id: str
) -> WorkItem | None:
    return await store.get_work_item_by_run_id(
        principal.tenant_id,
        run_id,
        workspace_id=principal.active_workspace_id,
        enforce_workspace=True,
    )


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
    item = await store.get_work_item_by_run_id(principal.tenant_id, run_id)
    if item is not None:
        item = await visible_work_item_by_run(store, principal, run_id)
        if item is None:
            return None
        if departments is not None and item.owner_member not in set(departments):
            return None
    elif departments is not None:
        return None

    if any(not _workspace_visible(principal, row) for row in rows):
        return None

    return rows


async def visible_audit_tree_events(
    store: RunEventStore,
    principal: RunEventPrincipal,
    root_run_id: str,
    *,
    audit_limit: int = 10_000,
) -> list[AuditEvent] | None:
    """Return only rows the caller may use to reconstruct an execution tree.

    Tree assembly recursively follows parent links, so authorising only the root
    still leaks hidden descendants. Filter every source row with the same strict
    run-id department predicate as audit search, plus its workspace predicate,
    before any node or aggregate is built.
    """
    departments = departments_for(principal.role, principal.scope)
    root_item = await store.get_work_item_by_run_id(
        principal.tenant_id, root_run_id
    )
    if root_item is not None:
        root_item = await visible_work_item_by_run(store, principal, root_run_id)
        if root_item is None:
            return None
        if departments is not None and root_item.owner_member not in set(departments):
            return None
    elif departments is not None:
        return None

    all_items = await store.list_work_items(principal.tenant_id)
    visible_items = await store.list_work_items(
        principal.tenant_id,
        departments=departments,
        workspace_id=principal.active_workspace_id,
        enforce_workspace=True,
    )
    visible_item_ids = {item.id for item in visible_items}
    visible_work_ids = {work_item_run_id(item) for item in visible_items}
    hidden_work_ids = {
        work_item_run_id(item)
        for item in all_items
        if item.id not in visible_item_ids
    }

    def _run_visible(run_id: str) -> bool:
        if run_id in hidden_work_ids:
            return False
        return departments is None or run_id in visible_work_ids

    rows = await store.audit_query(principal.tenant_id, limit=audit_limit)
    visible = []
    for row in rows:
        if (
            row.run_id is None
            or not _run_visible(row.run_id)
            or not _workspace_visible(principal, row)
        ):
            continue
        if row.parent_run_id is not None and not _run_visible(row.parent_run_id):
            row = replace(row, parent_run_id=None)
        visible.append(row)
    # Preserve legitimate child-only trees, but never let a visible child revive a
    # root whose own tenant rows exist and were removed by the caller's scope.
    own_rows_exist = any(row.run_id == root_run_id for row in rows)
    known = any(row.run_id == root_run_id for row in visible)
    if not own_rows_exist:
        known = any(row.parent_run_id == root_run_id for row in visible)
    return visible if known else None
