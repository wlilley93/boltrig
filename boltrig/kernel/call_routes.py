"""Authenticated browser/desktop realtime-call session routes (decision 0021)."""

from __future__ import annotations

import uuid
from dataclasses import replace

from fastapi import Depends
from fastapi.responses import JSONResponse

from boltrig.models import (
    Conversation,
    RealtimeCallEvent,
    RealtimeCallSession,
    canonical_concrete_verbs,
    utcnow,
)

from .call_gateway_routes import register_gateway_call_routes
from .call_route_support import (
    audit_call,
    call_view,
    event_view,
    media_url,
    mint_media_token,
)
from .call_profiles import resolve_call_profiles


async def _owned_call(kernel, principal, call_id: str):
    call = await kernel.store.get_realtime_call(principal.tenant_id, call_id)
    return call if call is not None and call.owner_id == principal.subject else None


async def _conversation_id(kernel, principal, requested: object) -> str | None:
    conversation_id = str(requested or "").strip()
    if conversation_id:
        conversation = await kernel.store.get_conversation(
            principal.tenant_id, conversation_id
        )
        return (
            conversation_id
            if conversation is not None and conversation.user_id == principal.subject
            else None
        )
    conversation_id = f"conv_{uuid.uuid4().hex}"
    await kernel.store.create_conversation(
        Conversation(
            id=conversation_id,
            tenant_id=principal.tenant_id,
            user_id=principal.subject,
            title="Voice call",
        )
    )
    return conversation_id


async def _tool_context(kernel, principal) -> dict:
    concrete = canonical_concrete_verbs(tuple(
        verb.id
        for verb in await kernel.store.list_verbs(principal.tenant_id)
        if principal.grants.permits(verb.id)
    ))
    return {
        "allow": list(concrete),
        "deny": [],
        "role": principal.role,
        "scope": dict(principal.scope),
        "workspace_id": principal.active_workspace_id,
        "on_behalf_of": principal.on_behalf_of,
    }


async def create_call(body: dict, kernel, principal) -> JSONResponse:
    profiles, reason = await resolve_call_profiles(kernel, principal, body)
    if profiles is None:
        return JSONResponse(
            {"status": "error", "reason": reason},
            status_code=409,
        )
    conversation_id = await _conversation_id(
        kernel, principal, body.get("conversation_id")
    )
    if conversation_id is None:
        return JSONResponse(
            {"status": "error", "reason": "conversation_not_found"}, status_code=404
        )
    current = await kernel.store.get_current_realtime_call(
        principal.tenant_id, principal.subject, conversation_id
    )
    if current is not None:
        return JSONResponse(
            {"status": "error", "reason": "call_already_active",
             "call": call_view(current)},
            status_code=409,
        )
    channels = [
        channel
        for channel in await kernel.store.list_channels(principal.tenant_id)
        if channel.enabled and channel.platform == "voice" and channel.transport == "socket"
    ]
    common = dict(
        id=f"call_{uuid.uuid4().hex}",
        tenant_id=principal.tenant_id,
        conversation_id=conversation_id,
        owner_id=principal.subject,
        participants=profiles["participants"],
        tool_context={
            **await _tool_context(kernel, principal),
            "provider_route": profiles["provider_route"],
        },
        run_id=f"callrun_{uuid.uuid4().hex}",
        agent_profile_id=profiles["agent_profile_id"],
        model_profile_id=profiles["model_profile_id"],
    )
    if not channels:
        return await _create_unavailable(kernel, principal, common)
    return await _create_live(kernel, principal, common, channels[0].id)


async def _create_unavailable(kernel, principal, common: dict) -> JSONResponse:
    call = RealtimeCallSession(
        **common,
        channel_id=None,
        status="realtime_unavailable",
        unavailable_reason="no_enabled_realtime_voice_channel",
    )
    await kernel.store.create_realtime_call(call)
    await audit_call(kernel, principal, "realtime_call.create", call)
    return JSONResponse({
        "call": call_view(call),
        "text_continuation_conversation_id": call.conversation_id,
    })


async def _create_live(
    kernel, principal, common: dict, channel_id: str
) -> JSONResponse:
    token, token_hash, expires_at = mint_media_token()
    call = RealtimeCallSession(
        **common,
        channel_id=channel_id,
        status="creating",
        media_token_hash=token_hash,
        media_token_expires_at=expires_at,
    )
    await kernel.store.create_realtime_call(call)
    await audit_call(kernel, principal, "realtime_call.create", call)
    return JSONResponse({
        "call": call_view(call),
        "media_token": token,
        "media_token_expires_at": expires_at.isoformat(),
        "websocket_url": media_url(call.id),
    }, status_code=201)


async def get_call(call_id: str, kernel, principal) -> JSONResponse:
    call = await _owned_call(kernel, principal, call_id)
    if call is None:
        return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
    return JSONResponse({"call": call_view(call)})


async def list_calls(
    limit: int, conversation_id: str | None, kernel, principal
) -> JSONResponse:
    calls = await kernel.store.list_realtime_calls(
        principal.tenant_id,
        principal.subject,
        max(1, min(limit, 100)),
        str(conversation_id).strip() if conversation_id else None,
    )
    return JSONResponse({"calls": [call_view(call) for call in calls]})


async def get_current_call(
    conversation_id: str | None, kernel, principal
) -> JSONResponse:
    call = await kernel.store.get_current_realtime_call(
        principal.tenant_id,
        principal.subject,
        str(conversation_id).strip() if conversation_id else None,
    )
    return JSONResponse({"call": call_view(call) if call is not None else None})


async def get_call_events(
    call_id: str, limit: int, kernel, principal
) -> JSONResponse:
    call = await _owned_call(kernel, principal, call_id)
    if call is None:
        return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
    events = await kernel.store.list_realtime_call_events(
        principal.tenant_id, call_id, max(1, min(limit, 500))
    )
    return JSONResponse({"events": [event_view(event) for event in events]})


async def get_call_usage(call_id: str, kernel, principal) -> JSONResponse:
    call = await _owned_call(kernel, principal, call_id)
    if call is None:
        return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
    usage = await kernel.store.summarize_realtime_call_usage(
        principal.tenant_id, call_id
    )
    return JSONResponse({"call_id": call_id, "usage": usage})


async def refresh_media_token(call_id: str, kernel, principal) -> JSONResponse:
    call = await _owned_call(kernel, principal, call_id)
    if call is None:
        return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
    if call.status in {"ended", "failed", "realtime_unavailable"} or not call.channel_id:
        return JSONResponse(
            {"status": "error", "reason": "call_not_reconnectable"}, status_code=409
        )
    token, token_hash, expires_at = mint_media_token()
    call = replace(
        call,
        status="reconnecting",
        media_token_hash=token_hash,
        media_token_expires_at=expires_at,
        updated_at=utcnow(),
    )
    await kernel.store.update_realtime_call(call)
    return JSONResponse({
        "call": call_view(call),
        "media_token": token,
        "media_token_expires_at": expires_at.isoformat(),
        "websocket_url": media_url(call.id),
    })


async def reopen_call(call_id: str, kernel, principal) -> JSONResponse:
    return await refresh_media_token(call_id, kernel, principal)


async def end_call(call_id: str, kernel, principal) -> JSONResponse:
    call = await _owned_call(kernel, principal, call_id)
    if call is None:
        return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
    if call.status == "ended":
        return JSONResponse({"call": call_view(call)})
    now = utcnow()
    call = replace(
        call, status="ended", media_token_hash=None, media_token_expires_at=None,
        ended_at=now, updated_at=now,
    )
    await kernel.store.update_realtime_call(call)
    await kernel.store.append_realtime_call_event(
        RealtimeCallEvent(
            id=f"callev_{uuid.uuid4().hex}",
            tenant_id=principal.tenant_id,
            call_id=call.id,
            type="ended",
            payload={"reason": "user_ended"},
        )
    )
    await audit_call(kernel, principal, "realtime_call.end", call)
    return JSONResponse({"call": call_view(call)})


def _create_endpoint(principal_dep, kernel_dep):
    async def endpoint(body: dict, k=kernel_dep, p=principal_dep):
        return await create_call(body, k, p)
    return endpoint


def _call_endpoint(handler, principal_dep, kernel_dep):
    async def endpoint(call_id: str, k=kernel_dep, p=principal_dep):
        return await handler(call_id, k, p)
    return endpoint


def _events_endpoint(principal_dep, kernel_dep):
    async def endpoint(call_id: str, limit: int = 500, k=kernel_dep, p=principal_dep):
        return await get_call_events(call_id, limit, k, p)
    return endpoint


def _list_endpoint(principal_dep, kernel_dep):
    async def endpoint(
        limit: int = 50, conversation_id: str | None = None,
        k=kernel_dep, p=principal_dep,
    ):
        return await list_calls(limit, conversation_id, k, p)
    return endpoint


def _current_endpoint(principal_dep, kernel_dep):
    async def endpoint(
        conversation_id: str | None = None, k=kernel_dep, p=principal_dep
    ):
        return await get_current_call(conversation_id, k, p)
    return endpoint


def register_call_routes(app, *, principal_dep, get_kernel) -> None:
    principal = Depends(principal_dep)
    kernel = Depends(get_kernel)
    app.add_api_route(
        "/v1/calls", _create_endpoint(principal, kernel),
        methods=["POST"], name="create_realtime_call",
    )
    app.add_api_route(
        "/v1/calls", _list_endpoint(principal, kernel),
        methods=["GET"], name="list_realtime_calls",
    )
    app.add_api_route(
        "/v1/calls/current", _current_endpoint(principal, kernel),
        methods=["GET"], name="get_current_realtime_call",
    )
    app.add_api_route(
        "/v1/calls/{call_id}", _call_endpoint(get_call, principal, kernel),
        methods=["GET"], name="get_realtime_call",
    )
    app.add_api_route(
        "/v1/calls/{call_id}/events", _events_endpoint(principal, kernel),
        methods=["GET"], name="list_realtime_call_events",
    )
    app.add_api_route(
        "/v1/calls/{call_id}/usage",
        _call_endpoint(get_call_usage, principal, kernel),
        methods=["GET"], name="get_realtime_call_usage",
    )
    app.add_api_route(
        "/v1/calls/{call_id}/media-token",
        _call_endpoint(refresh_media_token, principal, kernel),
        methods=["POST"], name="refresh_realtime_call_media",
    )
    app.add_api_route(
        "/v1/calls/{call_id}/reopen",
        _call_endpoint(reopen_call, principal, kernel),
        methods=["POST"], name="reopen_realtime_call",
    )
    app.add_api_route(
        "/v1/calls/{call_id}/end", _call_endpoint(end_call, principal, kernel),
        methods=["POST"], name="end_realtime_call",
    )
    register_gateway_call_routes(app, get_kernel=get_kernel)
