"""The work item - the source-agnostic normalised unit of work (S6.3, P10).

The fleet operates only on work items. Source queue tools (Jira, Monday, ...)
are input/output channels, never the fleet's view of work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from .base import HITLId, RunId, TenantId, UserId, WorkItemId, WorkspaceId, utcnow


class WorkStatus(str, Enum):
    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    BLOCKED = "blocked"
    AWAITING_HUMAN = "awaiting_human"
    DONE = "done"
    FAILED = "failed"
    # A cooperative, owner-only server-side cancel ([2026] VJS-COUNTY 6): a
    # terminal state written when a run is cancelled at a step boundary. It is
    # NEUTRAL - neither a success nor a failure (mirrors how AWAITING_HUMAN scores
    # neutral); the pump writes it in a finally so it is durable (D1/D4).
    CANCELLED = "cancelled"


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
    # deadlines, assignees, deps; trusted intake may add reserved channel-thread
    # and creator grant-ceiling snapshots. The fleet re-applies each as a
    # narrowing intersection before any delegated verb is dispatched and carries
    # them to follow-on work; caller/model values never replace those stamps.
    constraints: dict[str, Any] = field(default_factory=dict)
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
    workspace_id: WorkspaceId | None = None  # originating active workspace
    # Channel addressing (decision 0003, Phase 2). ``target`` is ROUTING DATA,
    # never authority: None / "cos" addresses the tier-1 chief of staff (the
    # default - the CoS routes the item); any other value names a tier-2
    # subagent/run the item is addressed to. It is resolved at intake from the
    # channel's config mapping (chat/thread id -> target) or an explicit target
    # the verified sender supplied; identity stays kernel-authoritative (the
    # binding rows), this only steers routing.
    target: str | None = None
    # The way back for round-trip integrity: {"channel_id", "thread", "sender"}
    # captured at intake so a reply / run-completion notification returns to the
    # surface + thread the triggering message came from (SEC-179).
    reply_route: dict[str, Any] | None = None


def work_item_run_id(item: WorkItem) -> RunId:
    """Return the durable run identity for spawned and pump-native work alike."""
    return item.hatchet_run_id or item.id


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
