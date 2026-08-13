"""Shared projections and bounded token/event helpers for realtime call routes."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta

from boltrig.models import (
    ActionType,
    AuditEvent,
    RealtimeCallEvent,
    RealtimeCallSession,
    utcnow,
)

MEDIA_TOKEN_TTL_SECONDS = 90
MAX_EVENT_PAYLOAD_BYTES = 32_000
MAX_TRANSCRIPT_CHARS = 8_000
MAX_USAGE_COUNTER = 10**15


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def call_view(call: RealtimeCallSession) -> dict:
    return {
        "id": call.id,
        "conversation_id": call.conversation_id,
        "run_id": call.run_id,
        "agent_profile_id": call.agent_profile_id,
        "model_profile_id": call.model_profile_id,
        "status": call.status,
        "provider_class": call.provider_class,
        "participants": list(call.participants),
        "started_at": call.started_at.isoformat() if call.started_at else None,
        "ended_at": call.ended_at.isoformat() if call.ended_at else None,
        "created_at": call.created_at.isoformat(),
        "updated_at": call.updated_at.isoformat(),
        "unavailable_reason": call.unavailable_reason,
    }


def event_view(event: RealtimeCallEvent) -> dict:
    return {
        "id": event.id,
        "call_id": event.call_id,
        "type": event.type,
        "participant_id": event.participant_id,
        "payload": dict(event.payload),
        "created_at": event.created_at.isoformat(),
    }


def media_url(call_id: str) -> str:
    base = os.environ.get("BOLTRIG_CALL_WEBSOCKET_BASE", "/voice/v1/calls").rstrip("/")
    return f"{base}/{call_id}/media"


def mint_media_token() -> tuple[str, str, datetime]:
    token = secrets.token_urlsafe(32)
    expires_at = utcnow() + timedelta(seconds=MEDIA_TOKEN_TTL_SECONDS)
    return token, token_digest(token), expires_at


def safe_gateway_payload(event_type: str, raw: object) -> dict | None:
    """Allow normalized text/metadata only; discard every media-shaped field."""
    payload = dict(raw) if isinstance(raw, dict) else {}
    allowed: dict[str, tuple[str, ...]] = {
        "participant_joined": ("label", "kind"),
        "participant_left": ("reason",),
        "transcript": ("text", "final", "kind", "via"),
        "tool_call": ("provider_call_id", "verb"),
        "tool_result": ("provider_call_id", "verb", "status", "reason"),
        "hitl": ("request_id", "status", "verb", "provider_call_id"),
        "usage": (
            "input_audio_bytes",
            "output_audio_bytes",
            "tool_calls",
            "provider_input_tokens",
            "provider_output_tokens",
            "estimated_cost_micros",
            "pricing_revision",
            "cost_status",
        ),
        "interrupted": ("reason",),
        "reconnected": ("reason",),
        "ended": ("reason",),
    }
    if event_type not in allowed:
        return None
    safe = {key: payload[key] for key in allowed[event_type] if key in payload}
    if "text" in safe:
        safe["text"] = str(safe["text"])[:MAX_TRANSCRIPT_CHARS]
    if "via" in safe:
        safe["via"] = str(safe["via"])[:20]
    if event_type == "transcript":
        if (
            safe.get("kind") not in {"input", "output"}
            or not isinstance(safe.get("final"), bool)
            or not str(safe.get("text") or "").strip()
        ):
            return None
    if event_type == "usage":
        for key in (
            "input_audio_bytes",
            "output_audio_bytes",
            "tool_calls",
            "provider_input_tokens",
            "provider_output_tokens",
            "estimated_cost_micros",
        ):
            value = safe.get(key, 0)
            if isinstance(value, bool) or not isinstance(value, int):
                return None
            if value < 0 or value > MAX_USAGE_COUNTER:
                return None
            safe[key] = value
        safe["pricing_revision"] = str(
            safe.get("pricing_revision") or "not_configured"
        )[:100]
        if safe.get("cost_status") not in {"estimated", "unpriced"}:
            return None
    try:
        encoded = json.dumps(safe, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError):
        return None
    return safe if len(encoded.encode("utf-8")) <= MAX_EVENT_PAYLOAD_BYTES else None


async def audit_call(kernel, principal, verb: str, call: RealtimeCallSession) -> None:
    await kernel.audit.write(
        AuditEvent(
            tenant_id=principal.tenant_id,
            ts=utcnow(),
            actor=principal.subject,
            actor_tier=principal.actor_tier,
            action_type=ActionType.TOOL_CALL,
            noun="realtime_call",
            verb=verb,
            status="ok",
            on_behalf_of=principal.on_behalf_of,
            workspace_id=principal.active_workspace_id,
            ip_address=principal.ip_address,
            user_agent=principal.user_agent,
            resource="realtime_call",
            resource_id=call.id,
            detail={"status": call.status, "conversation_id": call.conversation_id},
        )
    )
