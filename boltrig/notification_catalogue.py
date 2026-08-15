"""Authoritative notification events and caller-deliverable channel routes."""

from __future__ import annotations

from typing import Any

APPROVAL_EVENT = "approval"
ESCALATION_EVENT = "escalation"
HITL_EXPIRED_EVENT = "hitl_expired"
WORK_STATUS_EVENT = "work_status"

NOTIFICATION_EVENTS = (
    {
        "id": APPROVAL_EVENT,
        "label": "Approval requested",
        "description": "An action is paused waiting for a person.",
    },
    {
        "id": ESCALATION_EVENT,
        "label": "Escalation",
        "description": "A run needs human attention.",
    },
    {
        "id": HITL_EXPIRED_EVENT,
        "label": "Request expired",
        "description": "A human decision timed out unanswered.",
    },
    {
        "id": WORK_STATUS_EVENT,
        "label": "Work completed",
        "description": "A requested or automatic run reached a terminal state.",
    },
)
NOTIFICATION_EVENT_IDS = frozenset(event["id"] for event in NOTIFICATION_EVENTS)
NOTIFICATION_PLATFORM_ALIASES = {"teams": "msteams"}


async def notification_catalogue(
    store: Any, tenant_id: str, subject: str
) -> dict[str, list[dict[str, Any]]]:
    """Return only transports with a real durable delivery path for this user."""
    transports = []
    for channel in sorted(
        await store.list_channels(tenant_id), key=lambda item: (item.name, item.id)
    ):
        if not channel.enabled or channel.transport != "socket":
            continue
        targets = sorted({
            binding.external_user_id
            for binding in await store.list_channel_bindings(tenant_id, channel.id)
            if binding.subject == subject and binding.external_user_id
        })
        if not targets:
            continue
        transports.append({
            "id": channel.id,
            "platform": channel.platform,
            "label": channel.name,
            "delivery_mode": "durable_outbox",
            "targets": [
                {
                    "id": target,
                    "label": f"Verified {channel.platform} identity",
                }
                for target in targets
            ],
        })
    return {"events": [dict(event) for event in NOTIFICATION_EVENTS],
            "transports": transports}


async def resolve_notification_route(
    store: Any,
    tenant_id: str,
    subject: str,
    event_type: object,
    channel_id: object,
    target: object,
) -> tuple[str, str, str]:
    """Resolve one submitted route against the current caller catalogue."""
    event = str(event_type or "").strip()
    channel = str(channel_id or "").strip()
    wanted_target = str(target or "").strip()
    if event not in NOTIFICATION_EVENT_IDS:
        raise ValueError("notification event is not produced by this server")
    catalogue = await notification_catalogue(store, tenant_id, subject)
    transport = next(
        (item for item in catalogue["transports"] if item["id"] == channel), None
    )
    if transport is None:
        raise ValueError("notification transport is not deliverable for this user")
    targets = [str(item["id"]) for item in transport["targets"]]
    resolved_target = wanted_target or targets[0]
    if resolved_target not in targets:
        raise ValueError("notification target is not a verified route for this user")
    return event, channel, resolved_target


async def notification_preference_is_deliverable(
    store: Any, tenant_id: str, subject: str, preference: Any
) -> bool:
    """Report current delivery truth, including readable legacy platform rows."""
    if preference.event_type not in NOTIFICATION_EVENT_IDS:
        return False
    legacy_platform = NOTIFICATION_PLATFORM_ALIASES.get(
        preference.channel, preference.channel
    )
    for channel in await store.list_channels(tenant_id):
        if (
            not channel.enabled
            or channel.transport != "socket"
            or (
                preference.channel != channel.id
                and legacy_platform != channel.platform
            )
        ):
            continue
        if any(
            binding.subject == subject
            for binding in await store.list_channel_bindings(tenant_id, channel.id)
        ):
            return True
    return False


def notification_delivery_view(message: Any) -> dict[str, Any]:
    return {
        "id": message.id,
        "status": message.status,
        "updated_at": message.updated_at.isoformat() if message.updated_at else None,
    }
