"""Caller-owned settings, activity, export and regeneration routes."""

from __future__ import annotations

import unicodedata
from dataclasses import replace

from fastapi import Query, Request
from fastapi.responses import JSONResponse

from boltrig.models import UserSetting
from boltrig.models.workspace_settings import resolve_user_settings, storage_key
from boltrig.store import audit_read_contract as audit_pages

from .approval_posture import APPROVAL_POSTURE_SETTING
from .approval_posture_routes import register_approval_posture_routes
from .sensing_policy import SENSING_KEYS
from .sensing_routes import register_sensing_routes


def _preferred_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    name = " ".join(value.strip().split())
    if not 1 <= len(name) <= 80:
        return None
    if any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in name):
        return None
    return name


def _register_profile_route(app, P, K, audit, user_view) -> None:
    @app.patch("/v1/me/profile")
    async def update_my_profile(body: dict, k=K, p=P) -> JSONResponse:
        display_name = _preferred_name(body.get("display_name"))
        if display_name is None:
            return JSONResponse(
                {"status": "error", "reason": "display_name must be 1-80 safe characters"},
                status_code=400,
            )
        user = await k.store.get_user(p.tenant_id, p.subject)
        if user is None:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        updated = replace(user, display_name=display_name)
        await k.store.upsert_user(updated)
        await audit(k, p, "profile.update", {"fields": ["display_name"]})
        return JSONResponse({"status": "ok", "profile": user_view(updated)})


def _register_settings_routes(app, P, K, audit, user_view) -> None:
    @app.get("/v1/me/settings")
    async def get_settings(request: Request, k=K, p=P) -> dict:
        rows = await k.store.list_user_settings(p.tenant_id, p.subject)
        user = await k.store.get_user(p.tenant_id, p.subject)
        profile = user_view(user) if user else {
            "id": p.subject,
            "role": p.role,
            "scope": p.scope,
            "status": "active",
        }
        from boltrig.kernel.platform_routes._shared import platform_state

        defaults = dict(platform_state(request).get("user_defaults", {}))
        stored = {row.key: row.value for row in rows}
        # Workspace override, then user override, then tenant default. The
        # namespaced storage keys never surface under their raw names, so a
        # caller sees exactly the values the scope they are in will use.
        values, sources = resolve_user_settings(
            defaults, stored, p.active_workspace_id
        )
        return {
            "profile": profile,
            "active_workspace_id": p.active_workspace_id,
            "settings": values,
            "setting_sources": sources,
        }

    @app.put("/v1/me/settings")
    async def put_settings(body: dict, k=K, p=P) -> JSONResponse:
        updates = body.get("settings")
        if updates is None and "key" in body:
            updates = {body["key"]: body.get("value")}
        if not isinstance(updates, dict) or not updates:
            return JSONResponse(
                {"status": "error", "reason": "no settings provided"}, status_code=400
            )
        if APPROVAL_POSTURE_SETTING in updates:
            return JSONResponse(
                {
                    "status": "error",
                    "reason": "use the approval-posture endpoint",
                },
                status_code=400,
            )
        # The sensing keys are consent about the user's own hardware, validated
        # against published camera bindings and against whether presence has a
        # room-calibrated threshold. A validated route that can be bypassed by
        # writing its raw key through the generic bag is not a validated route.
        if SENSING_KEYS & set(updates):
            return JSONResponse(
                {"status": "error", "reason": "use the sensing endpoints"},
                status_code=400,
            )
        for key, value in updates.items():
            # A workspace-scoped key written from inside a workspace lands on
            # that workspace's key, so choosing a companion in one business does
            # not change the other. Every other key, and every write at org
            # scope, lands on the bare key exactly as before.
            await k.store.upsert_user_setting(
                UserSetting(
                    tenant_id=p.tenant_id,
                    user_id=p.subject,
                    key=storage_key(str(key), p.active_workspace_id),
                    value=value,
                )
            )
        keys = sorted(str(key) for key in updates)
        await audit(k, p, "settings.update", {"keys": keys})
        return JSONResponse({"status": "ok", "keys": keys})

def _register_activity_routes(app, P, K, audit) -> None:
    @app.get("/v1/me/activity")
    async def my_activity(
        limit: int = Query(
            audit_pages.DEFAULT_ACCOUNT_ACTIVITY_PAGE,
            ge=1,
            le=audit_pages.MAX_ACCOUNT_ACTIVITY_PAGE,
        ),
        offset: int = Query(0, ge=0, le=audit_pages.MAX_AUDIT_SEARCH_OFFSET),
        k=K,
        p=P,
    ) -> dict:
        events, next_offset = await k.store.account_activity_page(
            p.tenant_id, p.subject, limit=limit, offset=offset
        )
        return {
            "results": [
                {
                    "seq": event.seq,
                    "ts": event.ts.isoformat() if event.ts else None,
                    "verb": event.verb,
                    "status": event.status,
                    "run_id": event.run_id,
                }
                for event in events
            ],
            "limit": limit,
            "offset": offset,
            "next_offset": next_offset,
        }

    @app.get("/v1/me/export")
    async def my_export(k=K, p=P) -> dict:
        conversations = await k.store.list_conversations(p.tenant_id, p.subject)
        work = await k.store.list_work_items(p.tenant_id)
        settings = await k.store.list_user_settings(p.tenant_id, p.subject)
        await audit(k, p, "data.export", {"conversations": len(conversations)})
        return {
            "user": p.subject,
            "conversations": [
                {
                    "id": conversation.id,
                    "title": conversation.title,
                    "status": conversation.status.value,
                }
                for conversation in conversations
            ],
            "work_items": [
                {"id": item.id, "intent": item.intent, "status": item.status.value}
                for item in work
                if item.on_behalf_of == p.subject or item.owner_member == p.subject
            ],
            "settings": {setting.key: setting.value for setting in settings},
        }


def _register_regenerate_route(app, P, K, audit) -> None:
    @app.post("/v1/me/conversations/{conversation_id}/messages/{message_id}/regenerate")
    async def regenerate_message(
        conversation_id: str, message_id: str, request: Request, k=K, p=P
    ) -> JSONResponse:
        conversation = await k.store.get_conversation(p.tenant_id, conversation_id)
        if conversation is None:
            return JSONResponse(
                {"status": "error", "reason": "not_found"}, status_code=404
            )
        if conversation.user_id != p.subject:
            return JSONResponse(
                {"status": "denied", "reason": "not your conversation"},
                status_code=403,
            )
        chat = getattr(request.app.state, "chat", None)
        if chat is None:
            return JSONResponse(
                {"status": "error", "reason": "chat_unavailable"}, status_code=503
            )
        message, superseded_id = await chat.regenerate_turn(
            tenant_id=p.tenant_id,
            user_id=p.subject,
            role=p.role,
            conversation_id=conversation_id,
            target_message_id=message_id,
            grants=p.grants,
            workspace_id=p.active_workspace_id,
            scope=p.scope,
        )
        await k.store.mark_message_superseded(
            p.tenant_id, superseded_id, message.id
        )
        await audit(
            k,
            p,
            "data.conversation.message.supersede",
            {
                "conversation_id": conversation_id,
                "superseded": superseded_id,
                "superseded_by": message.id,
                "run_id": message.run_id,
            },
        )
        from boltrig.workflows import harvest_reuse_signal

        await harvest_reuse_signal(
            k,
            p.context(run_id=message.run_id),
            target=superseded_id,
            polarity="regression",
            kind="regenerate_superseded",
        )
        return JSONResponse(
            {
                "status": "ok",
                "conversation_id": conversation_id,
                "message_id": message.id,
                "superseded": superseded_id,
                "run_id": message.run_id,
            }
        )


def register_account_profile_routes(app, P, K, audit, user_view) -> None:
    _register_profile_route(app, P, K, audit, user_view)
    _register_settings_routes(app, P, K, audit, user_view)
    register_approval_posture_routes(app, P, K, audit)
    register_sensing_routes(app, P, K, audit)
    _register_activity_routes(app, P, K, audit)
    _register_regenerate_route(app, P, K, audit)
