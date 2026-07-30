"""Reauthorization, dispatch receipts, and occurrence recovery."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from boltrig.identity.provisioning import effective_grants_for_request
from boltrig.models import InvocationContext, WorkflowScheduleOccurrence

from .scheduler_cron import workflow_schedule_digest
from .snapshot import workflow_snapshot_digest

MAX_DISPATCH_ATTEMPTS = 3
MAX_RECOVERY_BATCH = 50


async def _authority_context(
    store: Any, schedule: Any
) -> tuple[InvocationContext | None, str | None]:
    subject = schedule.authority_subject
    if not subject:
        return None, "scheduling_authority_not_bound"
    user = await store.get_user(schedule.tenant_id, subject)
    if user is None or user.status != "active":
        return None, "scheduling_authority_revoked"
    if schedule.workspace_id is not None:
        member = await store.get_workspace_member(
            schedule.tenant_id, schedule.workspace_id, user.id
        )
        if member is None:
            return None, "scheduling_workspace_membership_revoked"
    current = await effective_grants_for_request(
        store, user, schedule.workspace_id
    )
    bounded = current.intersect(schedule.grant_ceiling)
    if not bounded.permits("control.workflow.trigger"):
        return None, "scheduling_trigger_grant_revoked"
    return (
        InvocationContext(
            tenant_id=schedule.tenant_id,
            on_behalf_of=user.id,
            workspace_id=schedule.workspace_id,
            grants=bounded,
            actor=user.id,
            actor_tier="human",
            extra={
                "principal_role": user.role,
                "principal_scope": dict(user.scope or {}),
                "workflow_schedule": True,
            },
        ),
        None,
    )


async def _available_workflow(store: Any, schedule: Any) -> tuple[Any | None, str | None]:
    workflow = next(
        (
            item
            for item in await store.list_workflows(schedule.tenant_id)
            if item.id == schedule.workflow_id
            and item.workspace_id == schedule.workspace_id
        ),
        None,
    )
    if workflow is None:
        return None, "scheduled_workflow_unavailable"
    lifecycle = workflow.definition.get("_boltrig_lifecycle")
    if isinstance(lifecycle, dict) and lifecycle.get("status") == "archived":
        return None, "scheduled_workflow_archived"
    return workflow, None


async def _finish_unrecoverable(
    store: Any,
    occurrence: WorkflowScheduleOccurrence,
    *,
    owner: str,
    reason: str,
) -> None:
    await store.finish_workflow_schedule_occurrence(
        occurrence.tenant_id,
        occurrence.workflow_id,
        occurrence.scheduled_for,
        lease_owner=owner,
        status="failed",
        engine_run_id=None,
        reason=reason,
    )


async def _record_dispatch_success(
    store: Any,
    occurrence: WorkflowScheduleOccurrence,
    *,
    owner: str,
    engine_run_id: str | None,
) -> tuple[bool, str, str | None]:
    finished = await store.finish_workflow_schedule_occurrence(
        occurrence.tenant_id,
        occurrence.workflow_id,
        occurrence.scheduled_for,
        lease_owner=owner,
        status="queued",
        engine_run_id=engine_run_id,
        reason=None,
    )
    if finished:
        await store.record_workflow_run(
            occurrence.tenant_id,
            occurrence.workflow_id,
            occurrence.run_id,
            "queued",
        )
        return True, "active", None
    settled = await store.get_workflow_schedule_occurrence(
        occurrence.tenant_id,
        occurrence.workflow_id,
        occurrence.scheduled_for,
    )
    if (
        settled is not None
        and settled.run_id == occurrence.run_id
        and settled.status in {"succeeded", "failed"}
    ):
        status = "completed" if settled.status == "succeeded" else "failed"
        await store.record_workflow_run(
            occurrence.tenant_id,
            occurrence.workflow_id,
            occurrence.run_id,
            status,
        )
        observed = "active" if settled.status == "succeeded" else "degraded"
        return True, observed, settled.reason
    return False, "claimed", None


async def _record_dispatch_failure(
    store: Any,
    occurrence: WorkflowScheduleOccurrence,
    *,
    owner: str,
) -> tuple[bool, str, str]:
    reason = "schedule_dispatch_failed"
    retryable = occurrence.attempts < MAX_DISPATCH_ATTEMPTS
    await store.finish_workflow_schedule_occurrence(
        occurrence.tenant_id,
        occurrence.workflow_id,
        occurrence.scheduled_for,
        lease_owner=owner,
        status="retryable" if retryable else "failed",
        engine_run_id=None,
        reason=reason,
    )
    return False, "degraded", reason


async def _dispatch_claimed_occurrence(
    store: Any,
    workflows: Any,
    schedule: Any,
    occurrence: WorkflowScheduleOccurrence,
    context: InvocationContext,
    *,
    owner: str,
) -> tuple[bool, str, str | None]:
    """Submit one claimed logical occurrence across an at-least-once boundary."""
    try:
        descriptor = await workflows.trigger(
            occurrence.tenant_id,
            occurrence.workflow_id,
            {
                "schedule": {
                    "cron": schedule.cron,
                    "timezone": schedule.timezone,
                    "scheduled_for": occurrence.scheduled_for.isoformat(),
                }
            },
            active_workspace_id=schedule.workspace_id,
            context=context,
            run_id=occurrence.run_id,
            expected_workflow_sha256=occurrence.workflow_sha256,
        )
    except Exception:
        return await _record_dispatch_failure(store, occurrence, owner=owner)
    return await _record_dispatch_success(
        store,
        occurrence,
        owner=owner,
        engine_run_id=descriptor.get("engine_run_id"),
    )


async def _recovery_inputs(
    store: Any,
    candidate: WorkflowScheduleOccurrence,
    schedules: dict[str, Any],
) -> tuple[Any | None, Any | None, str | None, InvocationContext | None, str | None]:
    schedule = schedules.get(candidate.workflow_id)
    workflow = None
    unavailable = "scheduled_workflow_unavailable"
    context = None
    authority_reason = "scheduling_authority_not_bound"
    if schedule is not None:
        workflow, unavailable = await _available_workflow(store, schedule)
        context, authority_reason = await _authority_context(store, schedule)
    return schedule, workflow, unavailable, context, authority_reason


async def _recover_occurrence(
    store: Any,
    workflows: Any,
    schedules: dict[str, Any],
    candidate: WorkflowScheduleOccurrence,
    *,
    executor: Any,
    owner: str,
    lease_seconds: int,
) -> tuple[bool, str | None, str | None]:
    schedule, workflow, unavailable, context, authority_reason = (
        await _recovery_inputs(store, candidate, schedules)
    )
    claimed_row, claimed = await store.claim_workflow_schedule_occurrence(
        replace(candidate, status="claimed", lease_owner=owner),
        lease_seconds=lease_seconds,
    )
    if not claimed:
        return False, None, None
    if schedule is None or workflow is None:
        await _finish_unrecoverable(
            store, claimed_row, owner=owner, reason=unavailable
        )
        return False, None, None
    if (
        claimed_row.workflow_sha256 != workflow_snapshot_digest(workflow)
        or claimed_row.schedule_sha256 != workflow_schedule_digest(schedule)
    ):
        await _finish_unrecoverable(
            store,
            claimed_row,
            owner=owner,
            reason="occurrence_snapshot_changed",
        )
        return False, None, None
    if context is None:
        reason = authority_reason or "scheduling_authority_revoked"
        await _finish_unrecoverable(store, claimed_row, owner=owner, reason=reason)
        return False, "needs_action", authority_reason
    if not bool(getattr(executor, "durable", False)):
        await _finish_unrecoverable(
            store,
            claimed_row,
            owner=owner,
            reason="durable_executor_required",
        )
        return False, None, None
    return await _dispatch_claimed_occurrence(
        store,
        workflows,
        schedule,
        claimed_row,
        context,
        owner=owner,
    )


async def recover_prior_occurrences(
    store: Any,
    tenant_id: str,
    workflows: Any,
    schedules: dict[str, Any],
    *,
    executor: Any,
    owner: str,
    lease_seconds: int,
) -> int:
    """Replay retryable/expired claims without creating a second run identity."""
    queued = 0
    recoverable = await store.list_recoverable_workflow_schedule_occurrences(
        tenant_id, limit=MAX_RECOVERY_BATCH
    )
    for candidate in recoverable:
        accepted, observed, reason = await _recover_occurrence(
            store,
            workflows,
            schedules,
            candidate,
            executor=executor,
            owner=owner,
            lease_seconds=lease_seconds,
        )
        queued += int(accepted)
        schedule = schedules.get(candidate.workflow_id)
        if schedule is not None and observed not in {None, "active"}:
            await store.observe_workflow_schedule(
                tenant_id,
                schedule.workflow_id,
                status=observed,
                reason=reason,
            )
    return queued
