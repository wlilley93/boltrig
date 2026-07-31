"""Durable, re-authorized cron reconciliation for stored workflow schedules."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from boltrig.models import WorkflowScheduleOccurrence, utcnow

from .scheduler_cron import (
    CronExpression as CronExpression,
    next_cron_occurrence,
    scheduled_run_id,
    scheduler_interval_from_env as scheduler_interval_from_env,
    scheduler_worker_id,
    workflow_schedule_digest,
)
from .scheduler_dispatch import (
    MAX_DISPATCH_ATTEMPTS as MAX_DISPATCH_ATTEMPTS,
    MAX_RECOVERY_BATCH as MAX_RECOVERY_BATCH,
    _authority_context,
    _available_workflow,
    _dispatch_claimed_occurrence,
    recover_prior_occurrences,
)
from .scheduler_state import workflow_schedule_state as workflow_schedule_state
from .snapshot import workflow_snapshot_digest

log = logging.getLogger("boltrig.workflow-scheduler")

MAX_CATCH_UP = 3
MAX_MANUAL_RETRIES = 3
DEFAULT_LEASE_SECONDS = 120


@dataclass(frozen=True)
class _DueResult:
    schedule: Any
    queued: int
    attempts: int


async def _ready_schedule(
    store: Any,
    tenant_id: str,
    schedule: Any,
    *,
    executor: Any,
) -> tuple[Any, Any] | None:
    workflow, unavailable = await _available_workflow(store, schedule)
    if unavailable is not None:
        await store.observe_workflow_schedule(
            tenant_id,
            schedule.workflow_id,
            status="unavailable",
            reason=unavailable,
        )
        return None
    context, authority_reason = await _authority_context(store, schedule)
    if context is None:
        await store.observe_workflow_schedule(
            tenant_id,
            schedule.workflow_id,
            status="needs_action",
            reason=authority_reason,
        )
        return None
    if not bool(getattr(executor, "durable", False)):
        await store.observe_workflow_schedule(
            tenant_id,
            schedule.workflow_id,
            status="unavailable",
            reason="durable_executor_required",
        )
        return None
    return workflow, context


async def _initialize_schedule(
    store: Any,
    schedule: Any,
    current: datetime,
) -> bool:
    if schedule.next_due_at is not None:
        return False
    next_due = next_cron_occurrence(schedule.cron, schedule.timezone, current)
    await store.upsert_workflow_schedule(
        replace(
            schedule,
            next_due_at=next_due,
            observed_status="active",
            observed_reason=None,
            observed_at=current,
        )
    )
    return True


async def _claim_due(
    store: Any,
    tenant_id: str,
    schedule: Any,
    workflow: Any,
    *,
    due: datetime,
    owner: str,
    lease_seconds: int,
) -> tuple[WorkflowScheduleOccurrence, bool]:
    return await store.claim_workflow_schedule_occurrence(
        WorkflowScheduleOccurrence(
            tenant_id=tenant_id,
            workflow_id=schedule.workflow_id,
            scheduled_for=due,
            run_id=scheduled_run_id(tenant_id, schedule.workflow_id, due),
            status="claimed",
            lease_owner=owner,
            workflow_sha256=workflow_snapshot_digest(workflow),
            schedule_sha256=workflow_schedule_digest(schedule),
        ),
        lease_seconds=lease_seconds,
    )


async def _advance_schedule(
    store: Any,
    tenant_id: str,
    schedule: Any,
    *,
    due: datetime,
    status: str,
    reason: str | None,
) -> Any | None:
    next_due = next_cron_occurrence(schedule.cron, schedule.timezone, due)
    advanced = await store.advance_workflow_schedule(
        tenant_id,
        schedule.workflow_id,
        expected_due_at=due,
        next_due_at=next_due,
        last_scheduled_for=due,
        status=status,
        reason=reason,
    )
    if not advanced:
        return None
    return await store.get_workflow_schedule(tenant_id, schedule.workflow_id)


async def _handle_existing(
    store: Any,
    tenant_id: str,
    schedule: Any,
    occurrence: WorkflowScheduleOccurrence,
    due: datetime,
) -> Any | None:
    if occurrence.status not in {"queued", "failed"}:
        return None
    status = "active" if occurrence.status == "queued" else "degraded"
    return await _advance_schedule(
        store,
        tenant_id,
        schedule,
        due=due,
        status=status,
        reason=occurrence.reason,
    )


async def _dispatch_due(
    store: Any,
    tenant_id: str,
    workflows: Any,
    schedule: Any,
    occurrence: WorkflowScheduleOccurrence,
    context: Any,
    *,
    owner: str,
) -> tuple[bool, Any | None]:
    accepted, status, reason = await _dispatch_claimed_occurrence(
        store,
        workflows,
        schedule,
        occurrence,
        context,
        owner=owner,
    )
    if not accepted:
        await store.observe_workflow_schedule(
            tenant_id,
            schedule.workflow_id,
            status="degraded",
            reason=reason,
        )
        latest = await store.get_workflow_schedule_occurrence(
            tenant_id, schedule.workflow_id, occurrence.scheduled_for
        )
        if latest is not None and latest.status == "retryable":
            return False, None
    advanced = await _advance_schedule(
        store,
        tenant_id,
        schedule,
        due=occurrence.scheduled_for,
        status=status,
        reason=reason,
    )
    return accepted, advanced


async def _run_due_occurrences(
    store: Any,
    tenant_id: str,
    workflows: Any,
    schedule: Any,
    workflow: Any,
    context: Any,
    *,
    current: datetime,
    owner: str,
    lease_seconds: int,
    max_catch_up: int,
) -> _DueResult:
    queued = attempts = 0
    cap = max(0, max_catch_up)
    while schedule.next_due_at <= current and attempts < cap:
        due = schedule.next_due_at.astimezone(UTC)
        occurrence, claimed = await _claim_due(
            store,
            tenant_id,
            schedule,
            workflow,
            due=due,
            owner=owner,
            lease_seconds=lease_seconds,
        )
        if not claimed:
            refreshed = await _handle_existing(
                store, tenant_id, schedule, occurrence, due
            )
            if refreshed is None:
                break
            schedule = refreshed
            attempts += 1
            continue
        accepted, refreshed = await _dispatch_due(
            store,
            tenant_id,
            workflows,
            schedule,
            occurrence,
            context,
            owner=owner,
        )
        queued += int(accepted)
        if refreshed is None:
            break
        schedule = refreshed
        attempts += 1
    return _DueResult(schedule, queued, attempts)


async def _finish_reconcile(
    store: Any,
    tenant_id: str,
    result: _DueResult,
    *,
    current: datetime,
    max_catch_up: int,
) -> None:
    schedule = result.schedule
    if (
        schedule.next_due_at is not None
        and schedule.next_due_at <= current
        and result.attempts >= max(0, max_catch_up)
    ):
        skipped_to = next_cron_occurrence(schedule.cron, schedule.timezone, current)
        await store.advance_workflow_schedule(
            tenant_id,
            schedule.workflow_id,
            expected_due_at=schedule.next_due_at,
            next_due_at=skipped_to,
            last_scheduled_for=schedule.last_scheduled_for,
            status="degraded",
            reason="missed_occurrences_truncated",
        )
    elif result.attempts == 0:
        await store.observe_workflow_schedule(
            tenant_id,
            schedule.workflow_id,
            status="active",
            reason=None,
        )


async def _reconcile_schedule(
    store: Any,
    tenant_id: str,
    workflows: Any,
    schedule: Any,
    *,
    executor: Any,
    current: datetime,
    owner: str,
    lease_seconds: int,
    max_catch_up: int,
) -> int:
    ready = await _ready_schedule(store, tenant_id, schedule, executor=executor)
    if ready is None:
        return 0
    workflow, context = ready
    if await _initialize_schedule(store, schedule, current):
        return 0
    result = await _run_due_occurrences(
        store,
        tenant_id,
        workflows,
        schedule,
        workflow,
        context,
        current=current,
        owner=owner,
        lease_seconds=lease_seconds,
        max_catch_up=max_catch_up,
    )
    await _finish_reconcile(
        store,
        tenant_id,
        result,
        current=current,
        max_catch_up=max_catch_up,
    )
    return result.queued


async def reconcile_workflow_schedules(
    store: Any,
    tenant_id: str,
    workflows: Any,
    *,
    executor: Any,
    now: datetime | None = None,
    worker_id: str | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    max_catch_up: int = MAX_CATCH_UP,
) -> int:
    """Reconcile due schedules once and return queued logical occurrences."""
    current = (now or utcnow()).astimezone(UTC)
    owner = worker_id or scheduler_worker_id()
    schedules = await store.list_workflow_schedules(tenant_id)
    queued = await recover_prior_occurrences(
        store,
        tenant_id,
        workflows,
        {schedule.workflow_id: schedule for schedule in schedules},
        executor=executor,
        owner=owner,
        lease_seconds=lease_seconds,
    )
    for schedule in schedules:
        queued += await _reconcile_schedule(
            store,
            tenant_id,
            workflows,
            schedule,
            executor=executor,
            current=current,
            owner=owner,
            lease_seconds=lease_seconds,
            max_catch_up=max_catch_up,
        )
    return queued
