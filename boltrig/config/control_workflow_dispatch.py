"""Single control-adapter dispatcher branch for governed workflows."""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import AdapterError, ErrorClass, Result
from boltrig.models import InvocationContext

from .control_approval import require_unchanged_approval_context
from .control_workflows import (
    change_workflow_lifecycle_record,
    retry_workflow_schedule_occurrence_record,
    schedule_workflow_record,
    upsert_workflow_record,
)
from .control_workflow_triggers import (
    change_workflow_trigger_record,
    create_workflow_trigger_record,
)

_MUTABLE_ACTIONS = frozenset(
    {
        "control.workflow.schedule",
        "control.workflow.schedule_occurrence.retry",
        "control.workflow.unschedule",
        "control.workflow.archive",
        "control.workflow.restore",
        "control.workflow.trigger",
        "control.workflow.execute",
        "control.workflow.trigger_binding.create",
        "control.workflow.trigger_binding.enable",
        "control.workflow.trigger_binding.disable",
        "control.workflow.trigger_binding.rotate",
    }
)
_LIFECYCLE_ACTIONS = frozenset(
    {
        "control.workflow.unschedule",
        "control.workflow.archive",
        "control.workflow.restore",
    }
)


async def _definition_mutation(
    store: Any,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
) -> Result | None:
    tenant = context.tenant_id
    if verb == "control.workflow.upsert":
        workflow = await upsert_workflow_record(
            store, tenant, params, workspace_id=context.workspace_id
        )
        return Result.success({"upserted": "workflow", "id": workflow.id})
    if verb == "control.workflow.schedule":
        schedule, schedule_state = await schedule_workflow_record(
            store, tenant, params, context=context
        )
        return Result.success(
            {
                "id": params["workflow_id"],
                "schedule": schedule,
                "schedule_state": schedule_state,
            }
        )
    if verb == "control.workflow.schedule_occurrence.retry":
        occurrence = await retry_workflow_schedule_occurrence_record(
            store,
            tenant,
            params,
            context=context,
        )
        return Result.success(
            {
                "workflow_id": occurrence.workflow_id,
                "scheduled_for": occurrence.scheduled_for.isoformat(),
                "run_id": occurrence.run_id,
                "occurrence_status": occurrence.status,
                "manual_retries": occurrence.manual_retries,
            }
        )
    if verb not in _LIFECYCLE_ACTIONS:
        return None
    workflow, lifecycle = await change_workflow_lifecycle_record(
        store,
        tenant,
        params["workflow_id"],
        verb.rsplit(".", 1)[-1],
        workspace_id=context.workspace_id,
    )
    return Result.success(
        {
            "id": workflow.id,
            "workflow_status": lifecycle.get("status", "active"),
            "schedule": lifecycle.get("schedule"),
        }
    )


def _trigger_output(
    tenant: str,
    trigger: Any,
    secret: str | None,
    *,
    include_webhook_path: bool,
) -> Result:
    output = {
        "trigger_id": trigger.id,
        "workflow_id": trigger.workflow_id,
        "source": trigger.source,
        "enabled": trigger.enabled,
    }
    if secret is not None:
        output["secret"] = secret
        if include_webhook_path:
            output["webhook_path"] = f"/v1/automation-hooks/{tenant}/{trigger.id}"
    return Result.success(output)


async def _trigger_binding_mutation(
    store: Any,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
) -> Result | None:
    if not verb.startswith("control.workflow.trigger_binding."):
        return None
    tenant = context.tenant_id
    if verb.endswith(".create"):
        trigger, secret = await create_workflow_trigger_record(
            store, tenant, params, context
        )
        include_webhook_path = secret is not None
    else:
        trigger, secret = await change_workflow_trigger_record(
            store, tenant, params, context, verb.rsplit(".", 1)[-1]
        )
        include_webhook_path = False
    return _trigger_output(
        tenant,
        trigger,
        secret,
        include_webhook_path=include_webhook_path,
    )


async def _available_workflow(
    store: Any, workflow_id: str, context: InvocationContext
) -> Result | None:
    candidate = next(
        (
            item
            for item in await store.list_workflows(context.tenant_id)
            if item.id == workflow_id
            and (
                item.workspace_id is None
                or item.workspace_id == context.workspace_id
            )
        ),
        None,
    )
    lifecycle = (
        candidate.definition.get("_boltrig_lifecycle")
        if candidate is not None
        else None
    )
    if isinstance(lifecycle, dict) and lifecycle.get("status") == "archived":
        return Result.failure(
            AdapterError(ErrorClass.UNAUTHORISED, "workflow_archived")
        )
    return None


async def _execute_workflow(
    store: Any,
    workflows: Any,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
) -> Result:
    workflow_id = params["workflow_id"]
    blocked = await _available_workflow(store, workflow_id, context)
    if blocked is not None:
        return blocked
    if workflows is None:
        return Result.failure(
            AdapterError(ErrorClass.UNAVAILABLE, "workflow library not wired")
        )
    inputs = params.get("inputs", {})
    if verb.endswith(".trigger"):
        output = await workflows.trigger(
            context.tenant_id,
            workflow_id,
            inputs,
            active_workspace_id=context.workspace_id,
            context=context,
        )
    else:
        output = await workflows.execute(
            context.tenant_id, workflow_id, inputs, context
        )
        await _record_stats(store, context.tenant_id, workflow_id, output)
    return Result.success(output)


async def execute_workflow_control(
    store: Any,
    workflows: Any,
    loader: Any,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
) -> Result | None:
    if verb in _MUTABLE_ACTIONS:
        await require_unchanged_approval_context(
            store, loader, verb, params, context
        )
    mutation = await _definition_mutation(store, verb, params, context)
    if mutation is not None:
        return mutation
    trigger = await _trigger_binding_mutation(store, verb, params, context)
    if trigger is not None:
        return trigger
    if verb in {"control.workflow.trigger", "control.workflow.execute"}:
        return await _execute_workflow(store, workflows, verb, params, context)
    return None


async def _record_stats(
    store: Any, tenant: str, workflow_id: str, output: dict[str, Any]
) -> None:
    run_id = output.get("run_id")
    if not run_id:
        return
    try:
        await store.record_workflow_run(
            tenant, workflow_id, run_id, output.get("status", "")
        )
    except Exception:
        pass  # Observability cannot invalidate an already-completed run.
