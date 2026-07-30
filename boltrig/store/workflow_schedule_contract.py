"""Store protocol for workflow schedule desired state and occurrence receipts."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from boltrig.models.workflow_schedules import (
    WorkflowSchedule,
    WorkflowScheduleOccurrence,
)


class WorkflowScheduleStoreContract(Protocol):
    async def upsert_workflow_schedule(
        self, schedule: WorkflowSchedule
    ) -> WorkflowSchedule: ...

    async def get_workflow_schedule(
        self, tenant_id: str, workflow_id: str
    ) -> WorkflowSchedule | None: ...

    async def list_workflow_schedules(
        self, tenant_id: str
    ) -> list[WorkflowSchedule]: ...

    async def delete_workflow_schedule(
        self, tenant_id: str, workflow_id: str
    ) -> None: ...

    async def observe_workflow_schedule(
        self,
        tenant_id: str,
        workflow_id: str,
        *,
        status: str,
        reason: str | None,
    ) -> WorkflowSchedule | None: ...

    async def advance_workflow_schedule(
        self,
        tenant_id: str,
        workflow_id: str,
        *,
        expected_due_at: datetime,
        next_due_at: datetime,
        last_scheduled_for: datetime | None,
        status: str,
        reason: str | None,
    ) -> bool: ...

    async def claim_workflow_schedule_occurrence(
        self,
        occurrence: WorkflowScheduleOccurrence,
        *,
        lease_seconds: int,
    ) -> tuple[WorkflowScheduleOccurrence, bool]: ...

    async def get_workflow_schedule_occurrence(
        self,
        tenant_id: str,
        workflow_id: str,
        scheduled_for: datetime,
    ) -> WorkflowScheduleOccurrence | None: ...

    async def list_workflow_schedule_occurrences(
        self,
        tenant_id: str,
        workflow_id: str,
        *,
        limit: int,
    ) -> list[WorkflowScheduleOccurrence]: ...

    async def list_recoverable_workflow_schedule_occurrences(
        self,
        tenant_id: str,
        *,
        limit: int,
    ) -> list[WorkflowScheduleOccurrence]: ...

    async def request_workflow_schedule_occurrence_retry(
        self,
        tenant_id: str,
        workflow_id: str,
        scheduled_for: datetime,
        *,
        run_id: str,
        workflow_sha256: str,
        schedule_sha256: str,
        max_manual_retries: int,
    ) -> WorkflowScheduleOccurrence | None: ...

    async def finish_workflow_schedule_occurrence(
        self,
        tenant_id: str,
        workflow_id: str,
        scheduled_for: datetime,
        *,
        lease_owner: str,
        status: str,
        engine_run_id: str | None,
        reason: str | None,
    ) -> bool: ...

    async def finish_workflow_schedule_outcome(
        self,
        tenant_id: str,
        run_id: str,
        *,
        status: str,
        reason: str | None,
    ) -> bool: ...
