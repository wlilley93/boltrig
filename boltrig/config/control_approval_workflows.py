"""Workflow, profile, model and evaluation approval fingerprints."""

from __future__ import annotations

from typing import Any

from boltrig.models import AdapterFailure, InvocationContext
from boltrig.workflows.snapshot import workflow_snapshot_digest

WORKFLOW_ACTIONS = frozenset(
    {
        "control.workflow.schedule",
        "control.workflow.schedule_occurrence.retry",
        "control.workflow.unschedule",
        "control.workflow.archive",
        "control.workflow.restore",
        "control.workflow.trigger",
        "control.workflow.execute",
    }
)
WORKFLOW_TRIGGER_BINDING_ACTIONS = frozenset(
    {
        "control.workflow.trigger_binding.create",
        "control.workflow.trigger_binding.enable",
        "control.workflow.trigger_binding.disable",
        "control.workflow.trigger_binding.rotate",
    }
)
CAPABILITY_ACTIONS = frozenset(
    {"control.capability.retire", "control.capability.restore"}
)
MODEL_ENDPOINT_ACTIONS = frozenset(
    {"control.model_endpoint.retire", "control.model_endpoint.restore"}
)
EVAL_CASE_ACTIONS = frozenset(
    {"control.eval_case.archive", "control.eval_case.restore"}
)


async def budget_context(
    store: Any, params: dict[str, Any], context: InvocationContext
) -> dict[str, Any]:
    budget = await store.get_budget(context.tenant_id, str(params["scope_id"]))
    if budget is None:
        return {"budget": None}
    return {
        "budget": {
            "id": budget.id,
            "scope_type": budget.scope_type,
            "window": budget.window,
            "hard_stop": budget.hard_stop,
            "token_limit": budget.token_limit,
            "cost_limit_micros": budget.cost_limit_micros,
            "spent_tokens": budget.spent_tokens,
            "spent_micros": budget.spent_micros,
            "usage_state": budget.usage_state,
            "window_key": budget.window_key,
            "window_started_at": (
                budget.window_started_at.isoformat()
                if budget.window_started_at is not None
                else None
            ),
            "window_ends_at": (
                budget.window_ends_at.isoformat()
                if budget.window_ends_at is not None
                else None
            ),
        }
    }


async def workflow_context(
    store: Any, verb: str, params: dict[str, Any], context: InvocationContext
) -> dict[str, Any]:
    workflow_id = params["workflow_id"]
    workflow = next(
        (
            item
            for item in await store.list_workflows(context.tenant_id)
            if item.id == workflow_id
            and (item.workspace_id is None or item.workspace_id == context.workspace_id)
        ),
        None,
    )
    if workflow is None:
        raise AdapterFailure(
            "workflow not found",
            status_code=404,
            reason="control_resource_not_found",
        )
    lifecycle = workflow.definition.get("_boltrig_lifecycle")
    if (
        verb
        in {
            "control.workflow.schedule",
            "control.workflow.schedule_occurrence.retry",
            "control.workflow.trigger",
            "control.workflow.execute",
        }
        and isinstance(lifecycle, dict)
        and lifecycle.get("status") == "archived"
    ):
        raise AdapterFailure(
            "workflow_archived", status_code=409, reason="workflow_archived"
        )
    fingerprint = {"workflow_sha256": workflow_snapshot_digest(workflow)}
    if verb != "control.workflow.schedule_occurrence.retry":
        return fingerprint
    return await _workflow_occurrence_context(
        store, params, context, fingerprint
    )


async def _workflow_occurrence_context(
    store: Any,
    params: dict[str, Any],
    context: InvocationContext,
    fingerprint: dict[str, Any],
) -> dict[str, Any]:
    from datetime import datetime

    from boltrig.workflows.scheduler import workflow_schedule_digest

    workflow_id = str(params["workflow_id"])
    try:
        scheduled_for = datetime.fromisoformat(str(params["scheduled_for"]))
    except (TypeError, ValueError) as exc:
        raise AdapterFailure(
            "invalid occurrence timestamp",
            status_code=400,
            reason="invalid_occurrence",
        ) from exc
    if scheduled_for.tzinfo is None:
        raise AdapterFailure(
            "invalid occurrence timestamp",
            status_code=400,
            reason="invalid_occurrence",
        )
    schedule = await store.get_workflow_schedule(
        context.tenant_id, workflow_id
    )
    occurrence = await store.get_workflow_schedule_occurrence(
        context.tenant_id, workflow_id, scheduled_for
    )
    if schedule is None or occurrence is None:
        raise AdapterFailure(
            "schedule occurrence not found",
            status_code=404,
            reason="control_resource_not_found",
        )
    if occurrence.run_id != str(params["run_id"]):
        raise AdapterFailure(
            "schedule occurrence not found",
            status_code=404,
            reason="control_resource_not_found",
        )
    current_schedule_sha256 = workflow_schedule_digest(schedule)
    if (
        occurrence.workflow_sha256 != fingerprint["workflow_sha256"]
        or occurrence.schedule_sha256 != current_schedule_sha256
    ):
        raise AdapterFailure(
            "schedule occurrence snapshot changed",
            status_code=409,
            reason="occurrence_snapshot_changed",
        )
    if occurrence.status != "failed":
        raise AdapterFailure(
            "only a terminal failed occurrence can be retried",
            status_code=409,
            reason="occurrence_not_terminal_failed",
        )
    return {
        **fingerprint,
        "schedule_sha256": current_schedule_sha256,
        "occurrence": {
            "scheduled_for": occurrence.scheduled_for.isoformat(),
            "run_id": occurrence.run_id,
            "status": occurrence.status,
            "workflow_sha256": occurrence.workflow_sha256,
            "schedule_sha256": occurrence.schedule_sha256,
            "attempts": occurrence.attempts,
            "manual_retries": occurrence.manual_retries,
        },
    }


async def workflow_trigger_binding_context(
    store: Any, verb: str, params: dict[str, Any], context: InvocationContext
) -> dict[str, Any]:
    fingerprint = await workflow_context(
        store,
        (
            "control.workflow.trigger"
            if verb.endswith(".create") or verb.endswith(".enable")
            else verb
        ),
        params,
        context,
    )
    if verb.endswith(".create"):
        return {**fingerprint, "trigger_binding": None}
    trigger = await store.get_workflow_trigger(
        context.tenant_id, str(params["trigger_id"])
    )
    if (
        trigger is None
        or trigger.workflow_id != params["workflow_id"]
        or (
            trigger.workspace_id is not None
            and trigger.workspace_id != context.workspace_id
        )
    ):
        raise AdapterFailure(
            "workflow trigger not found",
            status_code=404,
            reason="control_resource_not_found",
        )
    return {
        **fingerprint,
        "trigger_binding": {
            "id": trigger.id,
            "workflow_id": trigger.workflow_id,
            "workspace_id": trigger.workspace_id,
            "source": trigger.source,
            "owner_id": trigger.owner_id,
            "channel_id": trigger.channel_id,
            "enabled": trigger.enabled,
            "updated_at": (
                trigger.updated_at.isoformat() if trigger.updated_at else None
            ),
        },
    }


async def capability_context(
    store: Any, params: dict[str, Any], context: InvocationContext
) -> dict[str, Any]:
    capability = next(
        (
            item
            for item in await store.list_all_capabilities(context.tenant_id)
            if item.name == params["name"]
        ),
        None,
    )
    if capability is None:
        raise AdapterFailure(
            "capability not found",
            status_code=404,
            reason="control_resource_not_found",
        )
    return {
        "capability": {
            "name": capability.name,
            "runtime": capability.runtime,
            "supported_skills": capability.supported_skills,
            "max_depth": capability.max_depth,
            "is_ephemeral": capability.is_ephemeral,
            "cost_tier": capability.cost_tier,
            "model_endpoint": capability.model_endpoint,
            "vision_model_endpoint": capability.vision_model_endpoint,
            "source": capability.source,
            "is_active": capability.is_active,
        }
    }


def model_endpoint_view(endpoint: Any) -> dict[str, Any] | None:
    if endpoint is None:
        return None
    return {
        "id": endpoint.id,
        "kind": endpoint.kind,
        "model": endpoint.model,
        "base_url": endpoint.base_url,
        "fallback": endpoint.fallback,
        "data_class": endpoint.data_class,
        "is_active": endpoint.is_active,
        "modalities": list(endpoint.modalities),
    }


async def _model_endpoint_references(
    store: Any, endpoint_id: str, context: InvocationContext
) -> dict[str, list[str]]:
    capabilities = sorted(
        item.name
        for item in await store.list_all_capabilities(context.tenant_id)
        if item.model_endpoint == endpoint_id or item.vision_model_endpoint == endpoint_id
    )
    fallbacks = sorted(
        item.id
        for item in await store.list_model_endpoints(context.tenant_id)
        if item.id != endpoint_id and item.fallback == endpoint_id
    )
    return {"capabilities": capabilities, "fallbacks": fallbacks}


async def model_endpoint_context(
    store: Any, params: dict[str, Any], context: InvocationContext
) -> dict[str, Any]:
    endpoint_id = str(params["id"])
    endpoint = await store.get_model_endpoint(context.tenant_id, endpoint_id)
    if endpoint is None:
        raise AdapterFailure(
            "model endpoint not found",
            status_code=404,
            reason="control_resource_not_found",
        )
    fallback = (
        await store.get_model_endpoint(context.tenant_id, endpoint.fallback)
        if endpoint.fallback
        else None
    )
    return {
        "model_endpoint": model_endpoint_view(endpoint),
        "fallback_target": model_endpoint_view(fallback),
        "references": await _model_endpoint_references(store, endpoint_id, context),
    }


async def model_endpoint_upsert_context(
    store: Any, params: dict[str, Any], context: InvocationContext
) -> dict[str, Any]:
    endpoint_id = str(params["id"])
    fallback_id = str(params.get("fallback") or "").strip() or None
    if fallback_id == endpoint_id:
        raise AdapterFailure(
            "a model endpoint cannot fall back to itself",
            status_code=409,
            reason="model_endpoint_fallback_invalid",
        )
    fallback = (
        await store.get_model_endpoint(context.tenant_id, fallback_id)
        if fallback_id
        else None
    )
    if fallback_id and (fallback is None or not fallback.is_active):
        raise AdapterFailure(
            "fallback model endpoint is missing or retired",
            status_code=409,
            reason="model_endpoint_fallback_unavailable",
        )
    return {
        "model_endpoint": model_endpoint_view(
            await store.get_model_endpoint(context.tenant_id, endpoint_id)
        ),
        "fallback_target": model_endpoint_view(fallback),
    }


def _eval_case_view(case: Any) -> dict[str, Any] | None:
    if case is None:
        return None
    return {
        "id": case.id,
        "target_kind": case.target_kind,
        "target_ref": case.target_ref,
        "input": case.input,
        "assertions": case.assertions,
        "labels": case.labels,
        "is_active": case.is_active,
    }


async def eval_case_context(
    store: Any, params: dict[str, Any], context: InvocationContext
) -> dict[str, Any]:
    case = await store.get_eval_case(context.tenant_id, str(params["id"]))
    if case is None:
        raise AdapterFailure(
            "evaluation case not found",
            status_code=404,
            reason="control_resource_not_found",
        )
    return {"eval_case": _eval_case_view(case)}


async def eval_case_upsert_context(
    store: Any, params: dict[str, Any], context: InvocationContext
) -> dict[str, Any]:
    case_id = str(params.get("id") or "").strip()
    return {
        "eval_case": (
            _eval_case_view(await store.get_eval_case(context.tenant_id, case_id))
            if case_id
            else None
        )
    }
