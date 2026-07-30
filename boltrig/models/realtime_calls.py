"""Durable metadata and normalized events for realtime voice sessions.

The provider-side media stream is deliberately absent from these records.
Boltrig persists the call lifecycle, transcript text, tool/HITL event metadata,
and usage-safe facts only; raw microphone and synthesized audio never enter the
store (decision 0021).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .base import TenantId, UserId, utcnow


CALL_STATUSES: tuple[str, ...] = (
    "creating",
    "joining",
    "active",
    "reconnecting",
    "held",
    "ended",
    "realtime_unavailable",
    "failed",
)

CALL_EVENT_TYPES: tuple[str, ...] = (
    "participant_joined",
    "participant_left",
    "transcript",
    "tool_call",
    "tool_result",
    "hitl",
    "usage",
    "interrupted",
    "reconnected",
    "ended",
)


@dataclass
class RealtimeCallSession:
    id: str
    tenant_id: TenantId
    conversation_id: str
    owner_id: UserId
    channel_id: str | None
    status: str
    participants: list[dict[str, Any]] = field(default_factory=list)
    # Server-authored snapshot used only to mint the short-lived MCP token the
    # gateway receives after media-token redemption. Never returned to a client.
    tool_context: dict[str, Any] = field(default_factory=dict)
    provider_class: str = "realtime_voice"
    run_id: str | None = None
    # Governed selections are resolved server-side at creation and remain
    # durable so a browser reload cannot silently fall back to another agent or
    # provider model.
    agent_profile_id: str | None = None
    model_profile_id: str | None = None
    # Only a digest is persisted. The bearer is returned once to the browser.
    media_token_hash: str | None = None
    media_token_expires_at: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    unavailable_reason: str | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass
class RealtimeCallEvent:
    id: str
    tenant_id: TenantId
    call_id: str
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    participant_id: str | None = None
    created_at: datetime = field(default_factory=utcnow)
