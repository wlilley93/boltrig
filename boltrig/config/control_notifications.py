"""Governed notification preference and test-delivery operations."""

from __future__ import annotations

import uuid
from typing import Any, cast

from boltrig.models import ChannelOutboxMessage, NotificationPref

from boltrig.notification_catalogue import resolve_notification_route


async def _owned_preference(
    store: Any, tenant_id: str, subject: str, preference_id: str
) -> NotificationPref:
    preference = next(
        (
            item
            for item in await store.list_notification_prefs(tenant_id)
            if item.id == preference_id
        ),
        None,
    )
    if (
        preference is None
        or preference.scope_kind != "user"
        or preference.scope_ref != subject
    ):
        raise LookupError("notification preference not found")
    return cast(NotificationPref, preference)


async def route_notification_record(
    store: Any, tenant_id: str, params: dict[str, Any], *, context: Any
) -> NotificationPref:
    """Create or replace only an owned, currently deliverable notification route."""
    subject = context.on_behalf_of or context.actor
    preference_id = str(params.get("id") or "").strip()
    existing = (
        await _owned_preference(store, tenant_id, subject, preference_id)
        if preference_id
        else None
    )
    enabled = bool(params.get("enabled", True))
    event_type = params.get("event_type", existing.event_type if existing else None)
    channel = params.get("channel", existing.channel if existing else None)
    target = params.get("target", existing.target if existing else None)
    try:
        resolved = await resolve_notification_route(
            store, tenant_id, subject, event_type, channel, target
        )
    except ValueError:
        if not enabled and existing is not None and (
            str(event_type or "") == existing.event_type
            and str(channel or "") == existing.channel
            and (target or None) == existing.target
        ):
            resolved = (
                existing.event_type,
                existing.channel,
                existing.target or "",
            )
        else:
            raise
    preference = NotificationPref(
        id=preference_id or uuid.uuid4().hex,
        tenant_id=tenant_id,
        scope_kind="user",
        scope_ref=subject,
        event_type=resolved[0],
        channel=resolved[1],
        target=resolved[2] or None,
        enabled=enabled,
    )
    await store.upsert_notification_pref(preference)
    return preference


async def test_notification_record(
    store: Any, tenant_id: str, preference_id: str, *, context: Any
) -> dict[str, Any]:
    """Queue one static test through the existing credential-free channel outbox."""
    subject = context.on_behalf_of or context.actor
    preference = await _owned_preference(
        store, tenant_id, subject, preference_id
    )
    if not preference.enabled:
        raise ValueError("notification preference is disabled")
    event, channel_id, target = await resolve_notification_route(
        store,
        tenant_id,
        subject,
        preference.event_type,
        preference.channel,
        preference.target,
    )
    message = ChannelOutboxMessage(
        id=f"co_{uuid.uuid4().hex[:16]}",
        tenant_id=tenant_id,
        channel_id=channel_id,
        payload={
            "text": f"Boltrig test: {event}",
            "target": target,
            "event": event,
            "subject": subject,
            "test": True,
        },
    )
    await store.enqueue_channel_outbox(message)
    return {"delivery_id": message.id, "delivery_status": "queued"}


__all__ = ["route_notification_record", "test_notification_record"]
