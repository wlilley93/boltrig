"""Durable desired/observed state for governed workflow schedules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .grants import EMPTY_GRANTS, GrantSet


@dataclass
class WorkflowSchedule:
    """One active cron desire and its last scheduler observation.

    ``grant_ceiling`` is a captured ceiling, never a durable grant.  A scheduler
    must re-authorize ``authority_subject`` against the current User,
    workspace-membership and grants before every occurrence.
    """

    tenant_id: str
    workflow_id: str
    workspace_id: str | None
    cron: str
    timezone: str
    authority_subject: str | None = None
    grant_ceiling: GrantSet = field(default_factory=lambda: EMPTY_GRANTS)
    observed_status: str = "pending"
    observed_reason: str | None = None
    next_due_at: datetime | None = None
    last_scheduled_for: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    observed_at: datetime | None = None


@dataclass
class WorkflowScheduleOccurrence:
    """A lease-fenced, idempotent receipt for one cron occurrence."""

    tenant_id: str
    workflow_id: str
    scheduled_for: datetime
    run_id: str
    status: str
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    engine_run_id: str | None = None
    reason: str | None = None
    attempts: int = 0
    workflow_sha256: str | None = None
    schedule_sha256: str | None = None
    claimed_at: datetime | None = None
    enqueued_at: datetime | None = None
    outcome_at: datetime | None = None
    manual_retries: int = 0
    last_retry_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
