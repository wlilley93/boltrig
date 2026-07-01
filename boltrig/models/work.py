"""The work item - the source-agnostic normalised unit of work (S6.3, P10).

The fleet operates only on work items. Source queue tools (Jira, Monday, ...)
are input/output channels, never the fleet's view of work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .base import RunId, TenantId, UserId, WorkItemId


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
    # Beat 3 adds the work_items.degraded column; until then degradation is
    # surfaced on the chat reply + the AGENT_SPAWN audit row only (US-FLT-07).
