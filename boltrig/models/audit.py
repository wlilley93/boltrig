"""The audit event (S6.5).

Every kernel action writes one append-only, hash-chained audit row (SEC-16,
K-19). Bounded observability (K-20): no raw secrets, payloads, or identity -
the writer stores references, digests and a bounded preview only. See
``boltrig.kernel.audit`` for the chaining/scrubbing implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from .base import RunId, TenantId, UserId, WorkspaceId


class ActionType(str, Enum):
    TOOL_CALL = "tool_call"
    WORKFLOW_TRIGGER = "workflow_trigger"
    AGENT_SPAWN = "agent_spawn"
    HITL = "hitl"
    MODEL_CALL = "model_call"


class SecurityEventType(str, Enum):
    """The classes of security signal on the distinct SecurityEvent stream
    ([2026] VJS-COUNTY 9, D3). This is not a business action (that is the audit
    log); it is a security-relevant SIGNAL - a rejected credential, a throttle
    trip, a denied grant, a bad MCP token."""

    LOGIN_FAILURE = "login_failure"
    RATE_LIMIT_TRIP = "rate_limit_trip"
    PERMISSION_DENIED = "permission_denied"
    MCP_AUTH_FAILURE = "mcp_auth_failure"


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
    # Opbox-depth enrichment ([2026] VJS-COUNTY 9, D1). ALL nullable + backfilled
    # NULL, so a row written before these existed canonicalises byte-for-byte as
    # before and its hash stays valid (the chain is unchanged for old rows - the
    # writer only folds a field into the hash when it is non-None). ip/ua come from
    # the request, workspace_id from the InvocationContext, resource/resource_id
    # name the acted-on object (best-effort, NULL otherwise). Keys-only (K-20):
    # never a secret here.
    ip_address: str | None = None
    user_agent: str | None = None
    resource: str | None = None
    resource_id: str | None = None
    workspace_id: WorkspaceId | None = None
    # Hash-chain fields, filled by the audit writer (K-19). Not set by callers.
    seq: int | None = None
    prev_hash: str | None = None
    hash: str | None = None


@dataclass
class SecurityEvent:
    """A distinct, tamper-evident (hash-chained) security-signal row ([2026]
    VJS-COUNTY 9, D3). Same chaining pattern as ``AuditEvent`` (SEC-16/K-19) but a
    SEPARATE stream, so security signals (login failures, throttle trips, denied
    grants, bad MCP tokens) never mix with the business audit trail and can be
    watched on their own. Append-only, keys-only (K-20): the writer scrubs
    ``detail`` and the row never carries a secret / password / session token.
    ``ip_address`` / ``user_agent`` / ``workspace_id`` sit at the SAME depth as an
    enriched audit row so a security signal is as attributable as an action."""

    tenant_id: TenantId
    ts: datetime
    event_type: SecurityEventType
    reason: str  # a bounded, controlled label (never user-supplied secret text)
    actor: str | None = None  # the identity the signal is about, if known
    actor_tier: str | None = None
    workspace_id: WorkspaceId | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    resource: str | None = None
    resource_id: str | None = None
    on_behalf_of: UserId | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    # Hash-chain fields, filled by the security writer. Not set by callers.
    seq: int | None = None
    prev_hash: str | None = None
    hash: str | None = None


@dataclass
class AuditRollupAnchor:
    """A periodic per-org/workspace ROLLUP ANCHOR over a contiguous audit-chain
    segment ([2026] VJS-COUNTY 9, D4). ``rollup_root_hash`` is a deterministic
    digest over the segment [seq_start, seq_end], so an anchor lets a verifier
    confirm the segment has not been rewritten without re-hashing the entire
    chain. The LOCAL dev-fallback (``is_dev_fallback=True``) writes the anchor with
    no external call; ``rfc3161_token`` (an RFC3161 TSA timestamp) and
    ``kms_signature`` (an external KMS signature over the root hash) are a clean
    seam left NULL until a Principal wires the external credential."""

    tenant_id: TenantId
    seq_start: int
    seq_end: int
    rollup_root_hash: str
    anchored_at: datetime
    id: str | None = None
    workspace_id: WorkspaceId | None = None  # NULL = org-wide anchor over the tenant
    is_dev_fallback: bool = True
    rfc3161_token: str | None = None  # external TSA timestamp token (Principal dep)
    kms_signature: str | None = None  # external KMS signature over the root (Principal dep)
