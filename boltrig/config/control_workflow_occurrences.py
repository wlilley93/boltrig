"""Governed manual retry of exact durable workflow occurrences."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from boltrig.models import AdapterFailure, InvocationContext
from boltrig.workflows.scheduler import (
    MAX_MANUAL_RETRIES,
    _authority_context,
    workflow_schedule_digest,
)
from boltrig.workflows.snapshot import workflow_snapshot_digest


def _scheduled_for(params: dict[str, Any]) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(params["scheduled_for"]))
    except (TypeError, ValueError) as exc:
        raise AdapterFailure(
            "invalid occurrence timestamp",
            status_code=400,
            reason="invalid_occurrence",
        ) from exc
    if parsed.tzinfo is None:
        raise AdapterFailure(
            "invalid occurrence timestamp",
            status_code=400,
            reason="invalid_occurrence",
        )
    return parsed.astimezone(UTC)


async def _workflow_and_schedule(
    store: Any,
    tenant_id: str,
    workflow_id: str,
    context: InvocationContext,
) -> tuple[Any, Any]:
    workflow = next(
        (
            item
            for item in await store.list_workflows(tenant_id)
            if item.id == workflow_id
            and (
                item.workspace_id is None
                or item.workspace_id == context.workspace_id
            )
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
    if isinstance(lifecycle, dict) and lifecycle.get("status") == "archived":
        raise AdapterFailure(
            "workflow archived",
            status_code=409,
            reason="workflow_archived",
        )
    schedule = await store.get_workflow_schedule(tenant_id, workflow_id)
    if (
        schedule is None
        or schedule.workspace_id != context.workspace_id
        or schedule.authority_subject != context.actor
    ):
        raise AdapterFailure(
            "active caller-bound schedule not found",
            status_code=409,
            reason="schedule_not_retryable",
        )
    return workflow, schedule


async def _require_current_authority(
    store: Any, schedule: Any, context: InvocationContext
) -> None:
    authority, authority_reason = await _authority_context(store, schedule)
    if authority is None:
        raise AdapterFailure(
            "schedule authority is no longer active",
            status_code=409,
            reason=authority_reason or "scheduling_authority_revoked",
        )
    if not authority.grants.intersect(context.grants).permits(
        "control.workflow.trigger"
    ):
        raise AdapterFailure(
            "current request cannot trigger the scheduled workflow",
            status_code=403,
            reason="scheduling_trigger_grant_revoked",
        )


async def _validated_occurrence(
    store: Any,
    tenant_id: str,
    workflow_id: str,
    scheduled_for: datetime,
    params: dict[str, Any],
    workflow_sha256: str,
    schedule_sha256: str,
) -> Any:
    occurrence = await store.get_workflow_schedule_occurrence(
        tenant_id, workflow_id, scheduled_for
    )
    if occurrence is None or occurrence.run_id != str(params["run_id"]):
        raise AdapterFailure(
            "schedule occurrence not found",
            status_code=404,
            reason="control_resource_not_found",
        )
    if (
        occurrence.workflow_sha256 != workflow_sha256
        or occurrence.schedule_sha256 != schedule_sha256
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
    if occurrence.manual_retries >= MAX_MANUAL_RETRIES:
        raise AdapterFailure(
            "manual retry limit reached",
            status_code=409,
            reason="occurrence_retry_limit_reached",
        )
    return occurrence


async def retry_workflow_schedule_occurrence_record(
    store: Any,
    tenant_id: str,
    params: dict[str, Any],
    *,
    context: InvocationContext,
):
    """Queue an exact failed occurrence for canonical scheduler replay."""
    workflow_id = str(params["workflow_id"])
    scheduled_for = _scheduled_for(params)
    workflow, schedule = await _workflow_and_schedule(
        store, tenant_id, workflow_id, context
    )
    await _require_current_authority(store, schedule, context)
    workflow_sha256 = workflow_snapshot_digest(workflow)
    schedule_sha256 = workflow_schedule_digest(schedule)
    occurrence = await _validated_occurrence(
        store,
        tenant_id,
        workflow_id,
        scheduled_for,
        params,
        workflow_sha256,
        schedule_sha256,
    )
    retried = await store.request_workflow_schedule_occurrence_retry(
        tenant_id,
        workflow_id,
        scheduled_for,
        run_id=occurrence.run_id,
        workflow_sha256=workflow_sha256,
        schedule_sha256=schedule_sha256,
        max_manual_retries=MAX_MANUAL_RETRIES,
    )
    if retried is None:
        raise AdapterFailure(
            "schedule occurrence changed before retry",
            status_code=409,
            reason="occurrence_retry_conflict",
        )
    return retried
