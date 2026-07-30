"""Atomic governed Work writes, separate from the worker-owned update path."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from boltrig.models import WorkItem, WorkStatus, utcnow

from .work_items import work_item_from_row
from .workspace_scope import work_item_workspace_visible

MAX_GOVERNED_WORK_DEPTH = 32
MANUAL_STATUS_TRANSITIONS: dict[WorkStatus, frozenset[WorkStatus]] = {
    WorkStatus.PENDING: frozenset(
        {
            WorkStatus.BLOCKED,
            WorkStatus.AWAITING_HUMAN,
            WorkStatus.FAILED,
            WorkStatus.CANCELLED,
        }
    ),
    WorkStatus.BLOCKED: frozenset(
        {WorkStatus.PENDING, WorkStatus.FAILED, WorkStatus.CANCELLED}
    ),
    WorkStatus.AWAITING_HUMAN: frozenset(
        {
            WorkStatus.BLOCKED,
            WorkStatus.DONE,
            WorkStatus.FAILED,
            WorkStatus.CANCELLED,
        }
    ),
    WorkStatus.FAILED: frozenset({WorkStatus.PENDING}),
    WorkStatus.IN_FLIGHT: frozenset(),
    WorkStatus.DONE: frozenset(),
    WorkStatus.CANCELLED: frozenset(),
}


class WorkMutationConflict(Exception):
    """A concurrent executor or lifecycle write won the mutation race."""

def work_item_visible(
    item: WorkItem | None,
    workspace_id: str | None,
    departments: list[str] | None,
) -> bool:
    if item is None or not work_item_workspace_visible(item, workspace_id, True):
        return False
    return departments is None or item.owner_member in set(departments)
def work_item_active(item: WorkItem) -> bool:
    return item.status is WorkStatus.IN_FLIGHT or (
        item.lease_expires_at is not None and item.lease_expires_at > utcnow()
    )
def validate_manual_transition(current: WorkStatus, requested: WorkStatus) -> None:
    if requested is current:
        return
    if requested not in MANUAL_STATUS_TRANSITIONS.get(current, frozenset()):
        raise ValueError(
            f"illegal manual transition {current.value} -> {requested.value}"
        )
def _validate_owner(owner: str | None, departments: list[str] | None) -> None:
    if owner is not None and departments is not None and owner not in departments:
        raise PermissionError("work owner is outside the caller's department scope")
async def governed_create_work(
    store: Any,
    item: WorkItem,
    *,
    workspace_id: str | None,
    departments: list[str] | None,
) -> WorkItem:
    """Create a canonical internal item without source-system writeback."""
    if departments is not None and item.owner_member not in departments:
        raise PermissionError("work owner is outside the caller's department scope")
    if hasattr(store, "_work"):
        return _create_memory(store, item, workspace_id, departments)
    return await _create_postgres(store, item, workspace_id, departments)
def _create_memory(
    store: Any,
    item: WorkItem,
    workspace_id: str | None,
    departments: list[str] | None,
) -> WorkItem:
    key = (item.tenant_id, item.id)
    if key in store._work:
        raise WorkMutationConflict("work item id already exists")
    depth = 0
    if item.parent_id is not None:
        parent = store._work.get((item.tenant_id, item.parent_id))
        if not work_item_visible(parent, workspace_id, departments):
            raise LookupError("parent work item not found")
        depth = parent.depth + 1
    if depth > MAX_GOVERNED_WORK_DEPTH:
        raise ValueError("work tree depth limit exceeded")
    created = replace(item, depth=depth)
    store._work[key] = replace(created)
    return replace(created)
async def _insert_work_row(conn: Any, item: WorkItem) -> None:
    await conn.execute(
        """INSERT INTO work_items
             (id, tenant_id, workspace_id, source, source_id, intent, confidence,
              convergent, status, owner_member, parent_id, hatchet_run_id, depth,
              on_behalf_of, constraints, raw, attempts, degraded, result,
              lease_owner, lease_expires_at, target, reply_route)
           VALUES
             ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,
              $19,$20,$21,$22,$23)""",
        item.id,
        item.tenant_id,
        item.workspace_id,
        item.source,
        item.source_id,
        item.intent,
        item.confidence,
        item.convergent,
        item.status.value,
        item.owner_member,
        item.parent_id,
        item.hatchet_run_id,
        item.depth,
        item.on_behalf_of,
        item.constraints,
        item.raw,
        item.attempts,
        item.degraded,
        item.result,
        item.lease_owner,
        item.lease_expires_at,
        item.target,
        item.reply_route,
    )
async def _create_postgres(
    store: Any,
    item: WorkItem,
    workspace_id: str | None,
    departments: list[str] | None,
) -> WorkItem:
    async with store.with_tenant(item.tenant_id) as conn:
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            f"work:{item.tenant_id}",
        )
        if await conn.fetchrow(
            "SELECT id FROM work_items WHERE tenant_id=$1 AND id=$2",
            item.tenant_id,
            item.id,
        ):
            raise WorkMutationConflict("work item id already exists")
        depth = 0
        if item.parent_id is not None:
            row = await conn.fetchrow(
                "SELECT * FROM work_items WHERE tenant_id=$1 AND id=$2 FOR SHARE",
                item.tenant_id,
                item.parent_id,
            )
            parent = work_item_from_row(row)
            if not work_item_visible(parent, workspace_id, departments):
                raise LookupError("parent work item not found")
            depth = parent.depth + 1
        if depth > MAX_GOVERNED_WORK_DEPTH:
            raise ValueError("work tree depth limit exceeded")
        created = replace(item, depth=depth)
        await _insert_work_row(conn, created)
        return created
async def governed_mutate_work(
    store: Any,
    tenant_id: str,
    item_id: str,
    *,
    action: str,
    value: Any,
    workspace_id: str | None,
    departments: list[str] | None,
) -> WorkItem:
    """Mutate assignment, status, or parent through an atomic backend fence."""
    if action == "assign":
        _validate_owner(value, departments)
    if hasattr(store, "_work"):
        return _mutate_memory(
            store, tenant_id, item_id, action, value, workspace_id, departments
        )
    return await _mutate_postgres(
        store, tenant_id, item_id, action, value, workspace_id, departments
    )
def _visible_memory_item(
    store: Any,
    tenant_id: str,
    item_id: str,
    workspace_id: str | None,
    departments: list[str] | None,
) -> WorkItem:
    item = store._work.get((tenant_id, item_id))
    if not work_item_visible(item, workspace_id, departments):
        raise LookupError("work item not found")
    return item
def _memory_subtree(store: Any, tenant_id: str, item_id: str) -> list[WorkItem]:
    found: dict[str, WorkItem] = {}
    frontier = [item_id]
    while frontier:
        parent_id = frontier.pop()
        if parent_id in found:
            continue
        parent = store._work.get((tenant_id, parent_id))
        if parent is None:
            continue
        found[parent_id] = parent
        frontier.extend(
            item.id
            for (tenant, _), item in store._work.items()
            if tenant == tenant_id and item.parent_id == parent_id
        )
    return list(found.values())


def _reparent_memory(
    store: Any,
    item: WorkItem,
    parent_id: str | None,
    workspace_id: str | None,
    departments: list[str] | None,
) -> WorkItem:
    subtree = _memory_subtree(store, item.tenant_id, item.id)
    if any(not work_item_visible(row, workspace_id, departments) for row in subtree):
        raise LookupError("work subtree not found")
    if any(work_item_active(row) for row in subtree):
        raise WorkMutationConflict("actively leased or in-flight work cannot be reparented")
    parent = None
    if parent_id is not None:
        parent = _visible_memory_item(
            store, item.tenant_id, parent_id, workspace_id, departments
        )
        if parent.id in {row.id for row in subtree}:
            raise ValueError("work parent would create a cycle")
    new_depth = 0 if parent is None else parent.depth + 1
    delta = new_depth - item.depth
    if max(row.depth + delta for row in subtree) > MAX_GOVERNED_WORK_DEPTH:
        raise ValueError("work tree depth limit exceeded")
    for row in subtree:
        updated = replace(
            row,
            parent_id=parent_id if row.id == item.id else row.parent_id,
            depth=row.depth + delta,
        )
        store._work[(row.tenant_id, row.id)] = updated
    return replace(store._work[(item.tenant_id, item.id)])


def _mutate_memory(
    store: Any,
    tenant_id: str,
    item_id: str,
    action: str,
    value: Any,
    workspace_id: str | None,
    departments: list[str] | None,
) -> WorkItem:
    item = _visible_memory_item(
        store, tenant_id, item_id, workspace_id, departments
    )
    if action == "reparent":
        return _reparent_memory(store, item, value, workspace_id, departments)
    if work_item_active(item):
        raise WorkMutationConflict("actively leased or in-flight work cannot be mutated")
    if action == "assign":
        updated = replace(item, owner_member=value)
    elif action == "status":
        validate_manual_transition(item.status, value)
        updated = replace(item, status=value)
    else:
        raise ValueError("unknown work mutation")
    store._work[(tenant_id, item_id)] = updated
    return replace(updated)


async def _pg_subtree(conn: Any, tenant_id: str, item_id: str) -> list[WorkItem]:
    ids = await conn.fetch(
        """WITH RECURSIVE subtree(id) AS (
             SELECT id FROM work_items WHERE tenant_id=$1 AND id=$2
             UNION
             SELECT child.id FROM work_items child
             JOIN subtree parent ON child.parent_id=parent.id
             WHERE child.tenant_id=$1
           )
           SELECT id FROM subtree""",
        tenant_id,
        item_id,
    )
    rows = await conn.fetch(
        """SELECT * FROM work_items
           WHERE tenant_id=$1 AND id=ANY($2::text[]) FOR UPDATE""",
        tenant_id,
        [row["id"] for row in ids],
    )
    return [work_item_from_row(row) for row in rows]


async def _reparent_postgres(
    conn: Any,
    item: WorkItem,
    parent_id: str | None,
    workspace_id: str | None,
    departments: list[str] | None,
) -> WorkItem:
    subtree = await _pg_subtree(conn, item.tenant_id, item.id)
    if any(not work_item_visible(row, workspace_id, departments) for row in subtree):
        raise LookupError("work subtree not found")
    if any(work_item_active(row) for row in subtree):
        raise WorkMutationConflict("actively leased or in-flight work cannot be reparented")
    parent = None
    if parent_id is not None:
        parent = next((row for row in subtree if row.id == parent_id), None)
        if parent is not None:
            raise ValueError("work parent would create a cycle")
        parent = work_item_from_row(
            await conn.fetchrow(
                "SELECT * FROM work_items WHERE tenant_id=$1 AND id=$2 FOR SHARE",
                item.tenant_id,
                parent_id,
            )
        )
        if not work_item_visible(parent, workspace_id, departments):
            raise LookupError("parent work item not found")
    new_depth = 0 if parent is None else parent.depth + 1
    delta = new_depth - item.depth
    if max(row.depth + delta for row in subtree) > MAX_GOVERNED_WORK_DEPTH:
        raise ValueError("work tree depth limit exceeded")
    await conn.execute(
        """UPDATE work_items SET
             parent_id=CASE WHEN id=$2 THEN $3 ELSE parent_id END,
             depth=depth+$4, updated_at=now()
           WHERE tenant_id=$1 AND id=ANY($5::text[])""",
        item.tenant_id,
        item.id,
        parent_id,
        delta,
        [row.id for row in subtree],
    )
    return replace(item, parent_id=parent_id, depth=new_depth)


async def _mutate_postgres(
    store: Any,
    tenant_id: str,
    item_id: str,
    action: str,
    value: Any,
    workspace_id: str | None,
    departments: list[str] | None,
) -> WorkItem:
    async with store.with_tenant(tenant_id) as conn:
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            f"work:{tenant_id}",
        )
        item = work_item_from_row(
            await conn.fetchrow(
                "SELECT * FROM work_items WHERE tenant_id=$1 AND id=$2 FOR UPDATE",
                tenant_id,
                item_id,
            )
        )
        if not work_item_visible(item, workspace_id, departments):
            raise LookupError("work item not found")
        if action == "reparent":
            return await _reparent_postgres(
                conn, item, value, workspace_id, departments
            )
        if work_item_active(item):
            raise WorkMutationConflict(
                "actively leased or in-flight work cannot be mutated"
            )
        if action == "assign":
            field, next_value = "owner_member", value
        elif action == "status":
            validate_manual_transition(item.status, value)
            field, next_value = "status", value.value
        else:
            raise ValueError("unknown work mutation")
        row = await conn.fetchrow(
            f"""UPDATE work_items SET {field}=$3, updated_at=now()
                WHERE tenant_id=$1 AND id=$2 RETURNING *""",
            tenant_id,
            item_id,
            next_value,
        )
        return work_item_from_row(row)
