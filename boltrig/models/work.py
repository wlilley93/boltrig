"""The work item - the source-agnostic normalised unit of work (S6.3, P10).

The fleet operates only on work items. Source queue tools (Jira, Monday, ...)
are input/output channels, never the fleet's view of work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from .base import HITLId, RunId, TenantId, UserId, WorkItemId, utcnow


class WorkStatus(str, Enum):
    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    BLOCKED = "blocked"
    AWAITING_HUMAN = "awaiting_human"
    DONE = "done"
    FAILED = "failed"


@dataclass
class WorkItem:
    id: WorkItemId
    tenant_id: TenantId
    source: str  # 'jira' | 'monday' | 'opbox' | 'internal' | ...
    intent: str
    confidence: float  # 0.0-1.0; how well-specified the item is (FR-WRK-02)
    convergent: bool  # known/shrinking steps vs may-expand (J/EXE)
    status: WorkStatus = WorkStatus.PENDING
    source_id: str | None = None
    owner_member: str | None = None  # fleet member currently responsible
    parent_id: WorkItemId | None = None
    hatchet_run_id: RunId | None = None
    depth: int = 0
    constraints: dict[str, Any] = field(default_factory=dict)  # deadlines, assignees, deps
    raw: dict[str, Any] = field(default_factory=dict)  # original payload, preserved
    on_behalf_of: UserId | None = None
    # Durable delegation (Beat 3). A claim (claim_work_item) takes a lease: one
    # winner per item across concurrent claimers, an expired lease is
    # reclaimable (US-FLT-05). ``degraded`` persists degraded honesty on the
    # item itself (US-FLT-07); Beat 4's pump wires it from the spawn result.
    attempts: int = 0
    degraded: bool = False
    result: dict[str, Any] | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None


@dataclass
class RunCheckpoint:
    """A durable per-step checkpoint of a run - the resume seam for Beat 4's
    pump. Keyed (tenant_id, run_id, step); upserts are idempotent."""

    tenant_id: TenantId
    run_id: RunId
    step: str
    status: str  # 'started' | 'done' | 'awaiting_human' | 'failed'
    output: dict[str, Any] | None = None
    hitl_request_id: HITLId | None = None
    updated_at: datetime = field(default_factory=utcnow)
