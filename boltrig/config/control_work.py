"""Governed Work-item lifecycle operations."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from boltrig.kernel.work_authority import stamp_creator_ceiling
from boltrig.models import InvocationContext, WorkItem, WorkStatus
from boltrig.store.work_mutations import (
    WorkMutationConflict,
    governed_create_work,
    governed_mutate_work,
    work_item_active,
    work_item_visible,
)

from .control_safety import ControlConflict

_HIGH_WORK_VERBS = frozenset({"control.work.status", "control.work.reparent"})


def _scope(context: InvocationContext) -> tuple[list[str] | None, str | None]:
    from boltrig.identity.rbac import can_author, departments_for

    role = str((context.extra or {}).get("principal_role") or "")
    if not can_author(role):
        raise PermissionError("authoring/admin not permitted for this role")
    departments = departments_for(role, (context.extra or {}).get("principal_scope"))
    return departments, context.workspace_id


def _view(item: WorkItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "intent": item.intent,
        "status": item.status.value,
        "confidence": item.confidence,
        "convergent": item.convergent,
        "owner_member": item.owner_member,
        "source": item.source,
        "parent_id": item.parent_id,
        "hatchet_run_id": item.hatchet_run_id,
        "on_behalf_of": item.on_behalf_of,
        "depth": item.depth,
        "workspace_id": item.workspace_id,
    }


def _fingerprint(item: WorkItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "status": item.status.value,
        "owner_member": item.owner_member,
        "parent_id": item.parent_id,
        "depth": item.depth,
        "workspace_id": item.workspace_id,
        "attempts": item.attempts,
        "lease_owner": item.lease_owner,
        "lease_expires_at": (item.lease_expires_at.isoformat() if item.lease_expires_at else None),
        "active": work_item_active(item),
    }


async def _visible_item(
    store: Any,
    item_id: str,
    context: InvocationContext,
    departments: list[str] | None,
) -> WorkItem:
    item = await store.get_work_item(
        context.tenant_id,
        item_id,
        workspace_id=context.workspace_id,
        enforce_workspace=True,
    )
    if not work_item_visible(item, context.workspace_id, departments):
        raise LookupError("work item not found")
    return item


async def approval_work_context(
    store: Any,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
) -> dict[str, Any]:
    departments, _ = _scope(context)
    item = await _visible_item(store, str(params["item_id"]), context, departments)
    result = {"work_item": _fingerprint(item)}
    if verb == "control.work.reparent" and params.get("parent_id") is not None:
        parent = await _visible_item(store, str(params["parent_id"]), context, departments)
        result["parent_work_item"] = _fingerprint(parent)
    return result


async def _require_exact_approval(
    store: Any,
    loader: Any,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
) -> None:
    from .control_approval import require_unchanged_approval_context

    await require_unchanged_approval_context(store, loader, verb, params, context)


async def execute_work_operation(
    store: Any,
    loader: Any,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
) -> dict[str, Any] | None:
    if not verb.startswith("control.work."):
        return None
    departments, workspace_id = _scope(context)
    try:
        if verb == "control.work.create":
            intent = str(params["intent"]).strip()
            if not intent:
                raise ValueError("work intent must not be blank")
            item = WorkItem(
                id=f"work-{uuid4()}",
                tenant_id=context.tenant_id,
                workspace_id=workspace_id,
                source="internal",
                intent=intent,
                confidence=float(params.get("confidence", 1.0)),
                convergent=bool(params.get("convergent", False)),
                owner_member=params.get("owner_member"),
                parent_id=params.get("parent_id"),
                on_behalf_of=context.on_behalf_of or context.actor,
            )
            stamp_creator_ceiling(item, context.grants)
            created = await governed_create_work(
                store,
                item,
                workspace_id=workspace_id,
                departments=departments,
            )
            return {"item": _view(created)}
        if verb in _HIGH_WORK_VERBS:
            await _require_exact_approval(store, loader, verb, params, context)
        action = {
            "control.work.assign": "assign",
            "control.work.status": "status",
            "control.work.reparent": "reparent",
        }.get(verb)
        if action is None:
            return None
        value: Any = params.get("owner_member")
        if action == "status":
            value = WorkStatus(str(params["status"]))
        elif action == "reparent":
            value = params.get("parent_id")
        item = await governed_mutate_work(
            store,
            context.tenant_id,
            str(params["item_id"]),
            action=action,
            value=value,
            workspace_id=workspace_id,
            departments=departments,
        )
        return {"item": _view(item)}
    except WorkMutationConflict as exc:
        raise ControlConflict(str(exc)) from exc
