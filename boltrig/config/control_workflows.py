"""Governed workflow record and lifecycle operations."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from boltrig.models import (
    EMPTY_GRANTS,
    InvocationContext,
    WorkflowDefinition,
    WorkflowSchedule,
    WorkflowSource,
    utcnow,
)
from boltrig.workflows.scheduler import (
    next_cron_occurrence,
    workflow_schedule_state,
)
from boltrig.workflows.loop_contract import require_valid_loop_contract

from .control_workflow_occurrences import (
    retry_workflow_schedule_occurrence_record
    as retry_workflow_schedule_occurrence_record,
)


def _visible(item: WorkflowDefinition, workspace_id: str | None) -> bool:
    return item.workspace_id is None or item.workspace_id == workspace_id


async def upsert_workflow_record(
    store: Any,
    tenant_id: str,
    params: dict[str, Any],
    *,
    workspace_id: str | None,
) -> WorkflowDefinition:
    if "source" in params:
        raise ValueError("workflow source is kernel-owned")
    existing = next(
        (
            item
            for item in await store.list_workflows(tenant_id)
            if item.id == params["id"] and _visible(item, workspace_id)
        ),
        None,
    )
    definition = dict(params.get("definition", {}))
    require_valid_loop_contract(definition)
    if existing is not None:
        lifecycle = existing.definition.get("_boltrig_lifecycle")
        if lifecycle is not None:
            definition.setdefault("_boltrig_lifecycle", lifecycle)
        if "schedule" in existing.definition:
            definition.setdefault("schedule", existing.definition["schedule"])
    workflow = WorkflowDefinition(
        id=params["id"],
        tenant_id=tenant_id,
        version=params.get("version", "1.0.0"),
        source=(existing.source if existing is not None else WorkflowSource.PRECREATED),
        definition=definition,
        intent_tags=params.get("intent_tags", []),
        origin_task=existing.origin_task if existing is not None else None,
        workspace_id=workspace_id,
    )
    await store.upsert_workflow(workflow)
    return workflow


async def schedule_workflow_record(
    store: Any,
    tenant_id: str,
    params: dict[str, Any],
    *,
    context: InvocationContext,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from boltrig.workflows.generator import schedule_spec

    workflow = next(
        (
            item
            for item in await store.list_workflows(tenant_id)
            if item.id == params["workflow_id"]
            and _visible(item, context.workspace_id)
        ),
        None,
    )
    if workflow is None:
        raise LookupError("workflow not found")
    lifecycle = dict(workflow.definition.get("_boltrig_lifecycle") or {})
    if lifecycle.get("status") == "archived":
        raise ValueError("workflow_archived")
    schedule = schedule_spec(params["cron"], params.get("timezone", "UTC"))
    definition = dict(workflow.definition)
    definition["schedule"] = schedule
    definition["_boltrig_lifecycle"] = {**lifecycle, "status": "active", "schedule": schedule}
    await store.upsert_workflow(replace(workflow, definition=definition))

    # Capture a revocable human delegator only when one actually exists. The
    # snapshot is a ceiling; the worker re-authorizes current user, membership
    # and grants before every occurrence. Synthetic callers may still store the
    # desired schedule, but its observed state says needs_action and it cannot run.
    authority_subject = None
    grant_ceiling = EMPTY_GRANTS
    observed_status = "needs_action"
    observed_reason: str | None = "scheduling_authority_not_bound"
    owner = await store.get_user(tenant_id, context.actor)
    member_ok = True
    if owner is not None and context.workspace_id is not None:
        member_ok = (
            await store.get_workspace_member(
                tenant_id, context.workspace_id, owner.id
            )
            is not None
        )
    if (
        owner is not None
        and owner.status == "active"
        and member_ok
        and context.grants.permits("control.workflow.trigger")
    ):
        authority_subject = owner.id
        grant_ceiling = context.grants
        observed_status = "pending"
        observed_reason = None
    now = utcnow()
    desired = await store.upsert_workflow_schedule(
        WorkflowSchedule(
            tenant_id=tenant_id,
            workflow_id=workflow.id,
            workspace_id=workflow.workspace_id,
            cron=schedule["cron"],
            timezone=schedule["timezone"],
            authority_subject=authority_subject,
            grant_ceiling=grant_ceiling,
            observed_status=observed_status,
            observed_reason=observed_reason,
            next_due_at=next_cron_occurrence(
                schedule["cron"], schedule["timezone"], now
            ),
            observed_at=now,
        )
    )
    return schedule, workflow_schedule_state(desired)


async def change_workflow_lifecycle_record(
    store: Any,
    tenant_id: str,
    workflow_id: str,
    action: str,
    *,
    workspace_id: str | None,
) -> tuple[WorkflowDefinition, dict[str, Any]]:
    workflow = next(
        (
            item
            for item in await store.list_workflows(tenant_id)
            if item.id == workflow_id and _visible(item, workspace_id)
        ),
        None,
    )
    if workflow is None:
        raise LookupError("workflow not found")
    definition = dict(workflow.definition)
    lifecycle = dict(definition.get("_boltrig_lifecycle") or {})
    if action == "unschedule":
        definition.pop("schedule", None)
        lifecycle["schedule"] = None
        await store.delete_workflow_schedule(tenant_id, workflow_id)
    elif action == "archive":
        definition.pop("schedule", None)
        lifecycle.update({"status": "archived", "schedule": None})
        await store.delete_workflow_schedule(tenant_id, workflow_id)
    elif action == "restore":
        lifecycle["status"] = "active"
    else:
        raise ValueError("unsupported workflow lifecycle action")
    definition["_boltrig_lifecycle"] = lifecycle
    updated = replace(workflow, definition=definition)
    await store.upsert_workflow(updated)
    return updated, lifecycle
