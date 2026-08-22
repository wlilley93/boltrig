"""Kernel-authored provenance for work accepted from a messaging channel.

Provider payloads are untrusted data.  The kernel therefore copies only bounded
identifiers into a reserved work-item constraint and supplies the authoritative
tenant channel, provider, authenticated subject, and resolved routing target
itself.  The private stamp supports correlation and reply integrity; callers see
only :func:`public_channel_provenance`, which deliberately omits provider user,
message, and conversation identifiers.
"""

from __future__ import annotations

import json
from typing import Any

from boltrig.models import WorkItem
from boltrig.text_envelope import wrap_untrusted

CHANNEL_MESSAGE_PROVENANCE_KEY = "_channel_message_provenance_v1"
_SCHEMA = "boltrig.channel-message-provenance/v1"
_MAX_IDENTIFIER = 512

_PROVIDER_LABELS = {
    "discord": "Discord",
    "email": "Email",
    "generic": "Custom channel",
    # The current ``msteams`` provider is a signed-webhook compatibility
    # adapter, not a Teams Bot/Graph connection.  Its public label must not
    # overstate effective capability.
    "msteams": "Teams webhook",
    "signal": "Signal",
    "slack": "Slack",
    "telegram": "Telegram",
    "voice": "Voice",
    "webhook": "Webhook",
    "whatsapp": "WhatsApp",
}


def _bounded(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:_MAX_IDENTIFIER] if text else None


def stamp_channel_message_provenance(
    item: WorkItem,
    *,
    channel: Any,
    authenticated_subject: str,
    delivery_id: str,
    sender: str,
    target: str,
    reply_route: dict[str, Any],
    body: dict[str, Any],
) -> None:
    """Replace any caller-supplied reserved value with an authoritative stamp."""

    supplied = body.get("message_provenance")
    supplied = supplied if type(supplied) is dict else {}
    provider = _bounded(channel.platform) or "unknown"
    thread = _bounded(reply_route.get("thread"))
    item.constraints.pop(CHANNEL_MESSAGE_PROVENANCE_KEY, None)
    item.constraints[CHANNEL_MESSAGE_PROVENANCE_KEY] = {
        "schema": _SCHEMA,
        "direction": "inbound",
        # These four fields are derived after channel authentication and sender
        # binding.  They never come from the provider payload.
        "provider": provider,
        "channel_id": _bounded(channel.id),
        "channel_label": _bounded(channel.name) or _PROVIDER_LABELS.get(provider, provider),
        "authenticated_subject": _bounded(authenticated_subject),
        "routing_target": _bounded(target),
        # Exact provider identifiers remain private.  They are bounded, treated
        # as data, and exist only for diagnostics/correlation.
        "delivery_id": _bounded(delivery_id),
        "provider_message_id": _bounded(supplied.get("provider_message_id"))
        or _bounded(body.get("id")),
        "provider_sender_id": _bounded(supplied.get("provider_sender_id")) or _bounded(sender),
        "provider_conversation_id": _bounded(supplied.get("provider_conversation_id")) or thread,
        "provider_timestamp": _bounded(supplied.get("provider_timestamp")),
        "reply_thread": thread,
        "threaded": supplied.get("threaded") is True,
    }


def _private_stamp(item: WorkItem) -> dict[str, Any] | None:
    raw = (item.constraints or {}).get(CHANNEL_MESSAGE_PROVENANCE_KEY)
    if type(raw) is not dict or raw.get("schema") != _SCHEMA:
        return None
    return raw


def public_channel_provenance(item: WorkItem) -> dict[str, Any] | None:
    """Return the safe UI/API projection; never expose raw provider identities."""

    raw = _private_stamp(item)
    if raw is None:
        return None
    provider = _bounded(raw.get("provider")) or "unknown"
    channel_label = _bounded(raw.get("channel_label")) or _PROVIDER_LABELS.get(provider, provider)
    subject = _bounded(raw.get("authenticated_subject"))
    target = _bounded(raw.get("routing_target"))
    return {
        "schema": "channel_message_v1",
        "kind": "channel_message",
        "direction": "inbound",
        "provider": provider,
        "provider_label": _PROVIDER_LABELS.get(provider, provider.replace("_", " ").title()),
        "channel_id": _bounded(raw.get("channel_id")),
        "channel_label": channel_label,
        "display_label": f"{_PROVIDER_LABELS.get(provider, provider.title())} · {channel_label}",
        "from": {
            "kind": "authenticated_subject",
            "subject": subject,
            "label": subject,
        },
        "to": {
            "kind": "routing_target",
            "address": target,
            "label": target,
        },
        "threaded": raw.get("threaded") is True,
    }


def channel_provenance_prompt(item: WorkItem) -> str | None:
    """An explicitly untrusted prompt fragment describing the accepted surface."""

    public = public_channel_provenance(item)
    if public is None:
        return None
    return wrap_untrusted(
        "channel_message_provenance",
        "kernel",
        json.dumps(public, ensure_ascii=False, sort_keys=True),
    )


__all__ = [
    "CHANNEL_MESSAGE_PROVENANCE_KEY",
    "channel_provenance_prompt",
    "public_channel_provenance",
    "stamp_channel_message_provenance",
]
