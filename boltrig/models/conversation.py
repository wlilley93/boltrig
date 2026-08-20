"""Conversation models - human<->fleet chat threads (Round Two, S4 CONV).

A conversation is owned by a user and is tenant-isolated; only the owner and
appropriately-scoped roles may read it (SEC-25). Messages carry the fleet run
that produced the turn (link to the kanban, US-CONV-02) and any inline HITL
request, plus the structured render events for replay (US-CONV-03/05).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from .base import RunId, TenantId, UserId, utcnow


class ConversationStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"


class ConversationOrigin(str, Enum):
    """Who opened the conversation.

    ``ROUTINE`` is deliberately a conversation property, not a title convention:
    automated work must remain identifiable after a user renames the chat.
    """

    USER = "user"
    ROUTINE = "routine"


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


@dataclass
class Conversation:
    id: str
    tenant_id: TenantId
    user_id: UserId  # owner (RBAC: only owner + scoped roles, SEC-25)
    # Immutable durable routing identity. Nullable only while legacy rows are
    # reconciled after the named-agent registry is seeded (0084 compatibility).
    agent_address: str | None = None
    title: str | None = None
    status: ConversationStatus = ConversationStatus.ACTIVE
    origin: ConversationOrigin = ConversationOrigin.USER
    source_ref: str | None = None
    source_run_id: RunId | None = None
    companion_id: str | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass
class ConversationMessage:
    id: str
    conversation_id: str
    tenant_id: TenantId
    role: MessageRole
    content: str | None = None
    run_id: RunId | None = None  # the fleet run this turn produced/used
    hitl_request_id: str | None = None  # set when this message is an inline HITL prompt
    events: list[dict[str, Any]] = field(default_factory=list)  # render data (tool/subagent)
    # Inline, size-capped attachments carried on the message row itself
    # ([2026] VJS-COUNTY 3): each is a record dict {name, media_type, data (base64),
    # size} written/read ONLY via the message contract (add_message / list_messages).
    # This is an inline blob in the row, NOT an object store; see docs/decisions.
    attachments: list[dict[str, Any]] = field(default_factory=list)
    # Append-plus-supersede marker ([2026] VJS-COUNTY 4): when a later turn
    # regenerates this reply, this points at the id of the message that supersedes
    # it. A superseded message is frozen (only this marker is ever written) and is
    # filtered out of continuity - it is never presented as live.
    superseded_by: str | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class ConversationSummary:
    """A DERIVED, append-only compaction record over a conversation's older turns.

    Long conversations get expensive to compose verbatim every turn. A summary is
    a cheap derived view of the OLDER turns so the continuity composer can send
    ``[summary of older turns] + [recent verbatim tail]`` instead of the full
    history past a threshold (config-as-data on ``ChatConfig``).

    It is DERIVED data, never a mutation of the frozen message record: the
    append-only message history ([2026] VJS-COUNTY 4 froze message content) is
    left completely intact. A summary row is only ever INSERTED (never updated);
    a re-compaction appends a NEW row covering more messages, it does not edit an
    old one. ``up_to_message_id`` is the id of the LAST live message the summary
    covers - the split boundary the composer uses to divide older-vs-tail - and
    ``covered_count`` is how many live messages that boundary spans (used to pick
    the latest summary and to gate re-compaction). Tenant-isolated (SEC-08).
    """

    id: str
    conversation_id: str
    tenant_id: TenantId
    up_to_message_id: str  # split boundary: the last live message this summary covers
    covered_count: int  # number of live messages covered (latest-selection + re-compaction gate)
    summary: str  # the derived digest of the covered older turns (DATA, never instructions)
    created_at: datetime = field(default_factory=utcnow)
