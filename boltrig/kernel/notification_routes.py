"""Caller-scoped notification catalogue, preferences, and delivery receipts."""

from __future__ import annotations

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from boltrig.notification_catalogue import (
    NOTIFICATION_PLATFORM_ALIASES,
    notification_catalogue,
    notification_delivery_view,
    notification_preference_is_deliverable,
)

from .control_routes import dispatch_control_route


async def _preference_views(store, principal) -> list[dict]:
    preferences = [
        item
        for item in await store.list_notification_prefs(principal.tenant_id)
        if item.scope_kind == "user" and item.scope_ref == principal.subject
    ]
    deliveries = await store.list_notification_outbox(
        principal.tenant_id, principal.subject
    )
    platforms = {
        channel.id: channel.platform
        for channel in await store.list_channels(principal.tenant_id)
    }
    views = []
    for preference in preferences:
        legacy_platform = NOTIFICATION_PLATFORM_ALIASES.get(
            preference.channel, preference.channel
        )
        last_delivery = next(
            (
                delivery
                for delivery in deliveries
                if delivery.payload.get("event") == preference.event_type
                and (
                    delivery.channel_id == preference.channel
                    or platforms.get(delivery.channel_id) == legacy_platform
                )
                and (
                    preference.target is None
                    or delivery.payload.get("target") == preference.target
                )
            ),
            None,
        )
        views.append({
            "id": preference.id,
            "event_type": preference.event_type,
            "channel": preference.channel,
            "target": preference.target,
            "enabled": preference.enabled,
            "deliverable": await notification_preference_is_deliverable(
                store, principal.tenant_id, principal.subject, preference
            ),
            "last_delivery": (
                notification_delivery_view(last_delivery)
                if last_delivery is not None
                else None
            ),
        })
    return views


def register_notification_routes(app, principal_dep, get_kernel) -> None:
    P = Depends(principal_dep)
    K = Depends(get_kernel)

    @app.get("/v1/me/notifications")
    async def my_notifications(k=K, p=P) -> dict:
        return {
            "catalogue": await notification_catalogue(
                k.store, p.tenant_id, p.subject
            ),
            "prefs": await _preference_views(k.store, p),
        }

    @app.put("/v1/me/notifications")
    async def put_my_notifications(
        body: dict, request: Request, k=K, p=P
    ) -> JSONResponse:
        output, pending = await dispatch_control_route(
            k, p, "control.notification.route", body, request=request
        )
        if pending is not None:
            return pending
        return JSONResponse({"status": "ok", **(output or {})})

    @app.post("/v1/me/notifications/{preference_id}/test")
    async def test_my_notification(
        preference_id: str, request: Request, k=K, p=P
    ) -> JSONResponse:
        output, pending = await dispatch_control_route(
            k,
            p,
            "control.notification.test",
            {"id": preference_id},
            request=request,
        )
        if pending is not None:
            return pending
        return JSONResponse({"status": "ok", **(output or {})})


__all__ = ["register_notification_routes"]
