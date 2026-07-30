"""In-memory workflow schedule desired state and occurrence receipts."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from threading import Lock

from boltrig.models import GrantSet, utcnow


def _memory_tables(store):
    schedules = getattr(store, "_workflow_schedules", None)
    occurrences = getattr(store, "_workflow_schedule_occurrences", None)
    lock = getattr(store, "_workflow_schedule_lock", None)
    if schedules is None:
        schedules = {}
        store._workflow_schedules = schedules
    if occurrences is None:
        occurrences = {}
        store._workflow_schedule_occurrences = occurrences
    if lock is None:
        lock = Lock()
        store._workflow_schedule_lock = lock
    return schedules, occurrences, lock


def _copy_schedule(schedule):
    return replace(
        schedule,
        grant_ceiling=GrantSet.of(
            list(schedule.grant_ceiling.allow), list(schedule.grant_ceiling.deny)
        ),
    )


class WorkflowScheduleStoreMem:
    async def upsert_workflow_schedule(self, schedule):
        schedules, _, lock = _memory_tables(self)
        key = (schedule.tenant_id, schedule.workflow_id)
        with lock:
            existing = schedules.get(key)
            now = utcnow()
            saved = _copy_schedule(
                replace(
                    schedule,
                    created_at=(
                        existing.created_at if existing is not None else schedule.created_at or now
                    ),
                    updated_at=now,
                )
            )
            schedules[key] = saved
            return _copy_schedule(saved)

    async def get_workflow_schedule(self, tenant_id, workflow_id):
        schedules, _, _ = _memory_tables(self)
        item = schedules.get((tenant_id, workflow_id))
        return _copy_schedule(item) if item is not None else None

    async def list_workflow_schedules(self, tenant_id):
        schedules, _, _ = _memory_tables(self)
        rows = [row for (tenant, _), row in schedules.items() if tenant == tenant_id]
        rows.sort(key=lambda row: row.workflow_id)
        return [_copy_schedule(row) for row in rows]

    async def delete_workflow_schedule(self, tenant_id, workflow_id):
        schedules, _, lock = _memory_tables(self)
        with lock:
            schedules.pop((tenant_id, workflow_id), None)

    async def observe_workflow_schedule(self, tenant_id, workflow_id, *, status, reason):
        schedules, _, lock = _memory_tables(self)
        key = (tenant_id, workflow_id)
        with lock:
            schedule = schedules.get(key)
            if schedule is None:
                return None
            now = utcnow()
            saved = replace(
                schedule,
                observed_status=status,
                observed_reason=reason,
                observed_at=now,
                updated_at=now,
            )
            schedules[key] = saved
            return _copy_schedule(saved)

    async def advance_workflow_schedule(
        self,
        tenant_id,
        workflow_id,
        *,
        expected_due_at,
        next_due_at,
        last_scheduled_for,
        status,
        reason,
    ):
        schedules, _, lock = _memory_tables(self)
        key = (tenant_id, workflow_id)
        with lock:
            schedule = schedules.get(key)
            if schedule is None or schedule.next_due_at != expected_due_at:
                return False
            now = utcnow()
            schedules[key] = replace(
                schedule,
                next_due_at=next_due_at,
                last_scheduled_for=last_scheduled_for,
                observed_status=status,
                observed_reason=reason,
                observed_at=now,
                updated_at=now,
            )
            return True

    async def claim_workflow_schedule_occurrence(self, occurrence, *, lease_seconds):
        _, occurrences, lock = _memory_tables(self)
        key = (
            occurrence.tenant_id,
            occurrence.workflow_id,
            occurrence.scheduled_for,
        )
        with lock:
            existing = occurrences.get(key)
            now = utcnow()
            if existing is not None and not _may_reclaim(existing, occurrence, now):
                return replace(existing), False
            saved = replace(
                occurrence,
                status="claimed",
                lease_expires_at=now + timedelta(seconds=max(1, lease_seconds)),
                attempts=(existing.attempts if existing is not None else 0) + 1,
                claimed_at=now,
                created_at=(
                    existing.created_at if existing is not None else occurrence.created_at or now
                ),
                updated_at=now,
            )
            occurrences[key] = saved
            return replace(saved), True

    async def get_workflow_schedule_occurrence(self, tenant_id, workflow_id, scheduled_for):
        _, occurrences, _ = _memory_tables(self)
        existing = occurrences.get((tenant_id, workflow_id, scheduled_for))
        return replace(existing) if existing is not None else None

    async def list_workflow_schedule_occurrences(self, tenant_id, workflow_id, *, limit):
        _, occurrences, _ = _memory_tables(self)
        rows = [
            row
            for (tenant, workflow, _), row in occurrences.items()
            if tenant == tenant_id and workflow == workflow_id
        ]
        rows.sort(key=lambda row: row.scheduled_for, reverse=True)
        return [replace(row) for row in rows[: max(1, min(int(limit), 51))]]

    async def list_recoverable_workflow_schedule_occurrences(self, tenant_id, *, limit):
        _, occurrences, _ = _memory_tables(self)
        now = utcnow()
        rows = [
            row
            for (tenant, _, _), row in occurrences.items()
            if tenant == tenant_id and _is_recoverable(row, now)
        ]
        rows.sort(key=lambda row: (row.updated_at or now, row.workflow_id, row.scheduled_for))
        return [replace(row) for row in rows[: max(1, min(int(limit), 100))]]

    async def request_workflow_schedule_occurrence_retry(
        self,
        tenant_id,
        workflow_id,
        scheduled_for,
        *,
        run_id,
        workflow_sha256,
        schedule_sha256,
        max_manual_retries,
    ):
        _, occurrences, lock = _memory_tables(self)
        key = (tenant_id, workflow_id, scheduled_for)
        with lock:
            existing = occurrences.get(key)
            if not _may_retry(
                existing,
                run_id,
                workflow_sha256,
                schedule_sha256,
                max_manual_retries,
            ):
                return None
            now = utcnow()
            saved = replace(
                existing,
                status="retryable",
                reason="manual_retry_requested",
                manual_retries=existing.manual_retries + 1,
                last_retry_at=now,
                outcome_at=None,
                updated_at=now,
            )
            occurrences[key] = saved
            return replace(saved)

    async def finish_workflow_schedule_occurrence(
        self,
        tenant_id,
        workflow_id,
        scheduled_for,
        *,
        lease_owner,
        status,
        engine_run_id,
        reason,
    ):
        _, occurrences, lock = _memory_tables(self)
        key = (tenant_id, workflow_id, scheduled_for)
        with lock:
            existing = occurrences.get(key)
            if (
                existing is None
                or existing.status != "claimed"
                or existing.lease_owner != lease_owner
            ):
                return False
            now = utcnow()
            occurrences[key] = replace(
                existing,
                status=status,
                engine_run_id=engine_run_id,
                reason=reason,
                enqueued_at=now if status == "queued" else existing.enqueued_at,
                outcome_at=now if status == "failed" else existing.outcome_at,
                lease_owner=None,
                lease_expires_at=None,
                updated_at=now,
            )
            return True

    async def finish_workflow_schedule_outcome(self, tenant_id, run_id, *, status, reason):
        if status not in {"succeeded", "failed"}:
            return False
        _, occurrences, lock = _memory_tables(self)
        with lock:
            match = _find_outcome(occurrences, tenant_id, run_id, status)
            if match is None:
                return False
            key, existing = match
            now = utcnow()
            occurrences[key] = replace(
                existing,
                status=status,
                reason=reason,
                outcome_at=now,
                enqueued_at=existing.enqueued_at or now,
                lease_owner=None,
                lease_expires_at=None,
                updated_at=now,
            )
            return True


def _may_reclaim(existing, occurrence, now) -> bool:
    return (
        existing.run_id == occurrence.run_id
        and existing.workflow_sha256 == occurrence.workflow_sha256
        and existing.schedule_sha256 == occurrence.schedule_sha256
        and _is_recoverable(existing, now)
    )


def _is_recoverable(occurrence, now) -> bool:
    return occurrence.status == "retryable" or (
        occurrence.status == "claimed"
        and occurrence.lease_expires_at is not None
        and occurrence.lease_expires_at <= now
    )


def _may_retry(occurrence, run_id, workflow_sha256, schedule_sha256, max_manual_retries) -> bool:
    return (
        occurrence is not None
        and occurrence.status == "failed"
        and occurrence.run_id == run_id
        and occurrence.workflow_sha256 == workflow_sha256
        and occurrence.schedule_sha256 == schedule_sha256
        and occurrence.manual_retries < max(0, int(max_manual_retries))
    )


def _find_outcome(occurrences, tenant_id, run_id, status):
    return next(
        (
            (key, row)
            for key, row in occurrences.items()
            if key[0] == tenant_id
            and row.run_id == run_id
            and (
                row.status in {"claimed", "queued"}
                or (row.status == "failed" and status == "succeeded")
            )
        ),
        None,
    )


__all__ = ["WorkflowScheduleStoreMem"]
