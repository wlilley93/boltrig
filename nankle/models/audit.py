"""The audit event (S6.5).

Every kernel action writes one append-only, hash-chained audit row (SEC-16,
K-19). Bounded observability (K-20): no raw secrets, payloads, or identity -
the writer stores references, digests and a bounded preview only. See
``nankle.kernel.audit`` for the chaining/scrubbing implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from .base import RunId, TenantId, UserId


class ActionType(str, Enum):
    TOOL_CALL = "tool_call"
    WORKFLOW_TRIGGER = "workflow_trigger"
    AGENT_SPAWN = "agent_spawn"
    HITL = "hitl"
    MODEL_CALL = "model_call"


@dataclass
class AuditEvent:
    tenant_id: TenantId
    ts: datetime
    actor: str  # agent capability name or user id
    action_type: ActionType
    status: str  # ok | denied | degraded | error | pending_human | ...
    run_id: RunId | None = None
    parent_run_id: RunId | None = None
    actor_tier: str | None = None  # tier1 | tier2 | ephemeral | human
    depth: int | None = None
    noun: str | None = None
    verb: str | None = None
    target_adapter: str | None = None
    on_behalf_of: UserId | None = None  # delegated human identity, if any
    latency_ms: int | None = None
    tokens_used: int | None = None
    cost_micros: int | None = None  # attributed cost, millionths of currency unit
    skills_loaded: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)
    # Hash-chain fields, filled by the audit writer (K-19). Not set by callers.
    seq: int | None = None
    prev_hash: str | None = None
    hash: str | None = None
