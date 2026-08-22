"""``AgentMessage`` records durable named-agent peer messages and logical sessions.

Named agents are addressable, long-lived tier-1 peers.  Their model process is
allowed to come and go: continuity lives in an append-only message log plus
append-only derived summaries.  Ephemeral children deliberately have no row in
this model and therefore cannot acquire a mailbox address.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from .base import TenantId, utcnow

AGENT_ADDRESS_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,62}")
MAX_AGENT_MESSAGE_BYTES = 32 * 1024
MAX_AGENT_SUMMARY_BYTES = 16 * 1024


def _required(value: str, label: str, maximum: int) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{label} must be a non-empty string of at most {maximum} characters")


def _address(value: str, label: str = "agent address") -> None:
    if not isinstance(value, str) or AGENT_ADDRESS_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase address slug")


class AgentMessageKind(str, Enum):
    ASK = "ask"
    TELL = "tell"
    REPLY = "reply"


class AgentDeliveryStatus(str, Enum):
    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    DELIVERED = "delivered"
    FAILED = "failed"


class AgentTurnLane(str, Enum):
    """Source class for one serialized turn of a durable named identity.

    The values are deliberately transport-neutral. Chat, peer mail, routines,
    channel intake, and future room fan-out all reduce to one of these lanes;
    the scheduler does not need to know which product surface woke the agent.
    """

    INTERACTIVE = "interactive"
    PEER = "peer"
    BACKGROUND = "background"


@dataclass
class NamedAgent:
    """One durable, addressable tier-1 peer.

    ``scope_id`` preserves an organisation's department/workspace policy label;
    it is an authorization scope, not a serving tier or parent relationship.
    """

    tenant_id: TenantId
    address: str
    name: str
    runtime: str = "codex"
    model_endpoint: str | None = None
    supported_skills: list[str] = field(default_factory=lambda: ["*"])
    max_depth: int = 3
    cost_tier: str = "standard"
    purpose: str = ""
    brief: str = ""
    scope_id: str | None = None
    default_for_intake: bool = False
    enabled: bool = True
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        _required(str(self.tenant_id), "tenant_id", 256)
        _address(self.address)
        _required(self.name, "agent name", 128)
        if self.scope_id is not None:
            _address(self.scope_id, "agent scope_id")
        if self.runtime not in {"codex", "script", "python-script"}:
            raise ValueError("named agent runtime is invalid")
        if not 1 <= self.max_depth <= 5:
            raise ValueError("named agent max_depth must be between 1 and 5")
        if not 1 <= len(self.supported_skills) <= 64:
            raise ValueError("named agent supported_skills must contain 1-64 entries")
        if any(not isinstance(item, str) or not item.strip() or len(item) > 128 for item in self.supported_skills):
            raise ValueError("named agent supported_skills contains an invalid entry")
        if len(self.purpose) > 500 or len(self.brief) > 8000:
            raise ValueError("named agent prompt policy is too large")


@dataclass(frozen=True)
class AgentMessage:
    """An immutable peer-message envelope.

    Delivery state is intentionally absent.  Claims and retries mutate the
    separate :class:`AgentDelivery`; the authored envelope never changes.
    ``authority`` is the captured invocation-context envelope and can only
    narrow the receiver's later tool authority.
    """

    id: str
    tenant_id: TenantId
    conversation_id: str
    sender: str
    recipient: str
    kind: AgentMessageKind
    content: str
    reply_to: str | None = None
    correlation_id: str | None = None
    run_id: str | None = None
    authority: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        _required(self.id, "agent message id", 128)
        _required(self.conversation_id, "agent conversation id", 128)
        _address(self.sender, "sender")
        _address(self.recipient, "recipient")
        if self.sender == self.recipient:
            raise ValueError("an agent message recipient must be a peer")
        if not isinstance(self.kind, AgentMessageKind):
            object.__setattr__(self, "kind", AgentMessageKind(self.kind))
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("agent message content is required")
        if len(self.content.encode("utf-8")) > MAX_AGENT_MESSAGE_BYTES:
            raise ValueError("agent message content exceeds the byte limit")
        if not isinstance(self.authority, dict):
            raise ValueError("agent message authority must be an object")


@dataclass
class AgentDelivery:
    tenant_id: TenantId
    message_id: str
    recipient: str
    status: AgentDeliveryStatus = AgentDeliveryStatus.PENDING
    attempts: int = 0
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    available_at: datetime | None = None
    last_error: str | None = None
    delivered_at: datetime | None = None
    updated_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        _address(self.recipient, "delivery recipient")
        if not isinstance(self.status, AgentDeliveryStatus):
            self.status = AgentDeliveryStatus(self.status)
        if self.attempts < 0:
            raise ValueError("delivery attempts cannot be negative")


@dataclass(frozen=True)
class AgentTurnLease:
    """A fenced lease for the one active turn of a named identity."""

    tenant_id: TenantId
    agent_address: str
    owner: str
    token: str
    lane: AgentTurnLane
    expires_at: datetime

    def __post_init__(self) -> None:
        _required(str(self.tenant_id), "tenant_id", 256)
        _address(self.agent_address)
        _required(self.owner, "agent turn owner", 256)
        _required(self.token, "agent turn lease token", 128)
        if not isinstance(self.lane, AgentTurnLane):
            object.__setattr__(self, "lane", AgentTurnLane(self.lane))
        if self.expires_at.tzinfo is None:
            raise ValueError("agent turn lease expiry must be timezone-aware")


@dataclass(frozen=True)
class ClaimedAgentMessage:
    message: AgentMessage
    delivery: AgentDelivery
    turn_lease: AgentTurnLease


@dataclass
class AgentSession:
    """A durable logical session for one named agent in one peer dialogue."""

    id: str
    tenant_id: TenantId
    agent_address: str
    conversation_id: str
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        _required(self.id, "agent session id", 128)
        _address(self.agent_address)
        _required(self.conversation_id, "agent conversation id", 128)


@dataclass(frozen=True)
class AgentSessionSummary:
    """``AgentSessionSummary`` is append-only compaction over older messages."""

    id: str
    tenant_id: TenantId
    session_id: str
    up_to_message_id: str
    covered_count: int
    summary: str
    created_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        _required(self.id, "agent session summary id", 128)
        _required(self.session_id, "agent session id", 128)
        _required(self.up_to_message_id, "summary boundary message id", 128)
        if self.covered_count <= 0:
            raise ValueError("agent session summary must cover at least one message")
        if len(self.summary.encode("utf-8")) > MAX_AGENT_SUMMARY_BYTES:
            raise ValueError("agent session summary exceeds the byte limit")


__all__ = [
    "AGENT_ADDRESS_RE",
    "MAX_AGENT_MESSAGE_BYTES",
    "AgentDelivery",
    "AgentDeliveryStatus",
    "AgentMessage",
    "AgentMessageKind",
    "AgentSession",
    "AgentSessionSummary",
    "AgentTurnLane",
    "AgentTurnLease",
    "ClaimedAgentMessage",
    "NamedAgent",
]
