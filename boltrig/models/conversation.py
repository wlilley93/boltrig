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
    title: str | None = None
    status: ConversationStatus = ConversationStatus.ACTIVE
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
