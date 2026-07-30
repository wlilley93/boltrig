"""Run-token-authenticated media redemption and event links for the gateway."""

from __future__ import annotations

import uuid
from dataclasses import replace

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from boltrig.models import (
    CALL_EVENT_TYPES,
    GrantSet,
    RealtimeCallEvent,
    utcnow,
)

from .call_route_support import (
    call_view,
    event_view,
    safe_gateway_payload,
    token_digest,
)
from .call_transcript import project_call_transcript

_GATEWAY_TOKEN_HEADER = "x-boltrig-mcp-token"


def _gateway_token(request: Request, kernel):
    token = kernel.mcp.lookup_run_token(request.headers.get(_GATEWAY_TOKEN_HEADER))
    if token is None or not (token.extra or {}).get("channel_gateway"):
        return None
    from boltrig.store.postgres import set_current_tenant

    set_current_tenant(token.tenant_id)
    return token


async def _owns_call_channel(kernel, gateway, call) -> bool:
    return bool(
        call is not None
        and call.channel_id in set((gateway.extra or {}).get("channels") or [])
        and await kernel.store.channel_gateway_lease_owned(
            gateway.tenant_id,
            call.channel_id,
            gateway.lease_id,
        )
    )


async def claim_call_media(body: dict, request: Request, kernel) -> JSONResponse:
    gateway = _gateway_token(request, kernel)
    if gateway is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    call_id = str(body.get("call_id") or "")
    raw_token = str(body.get("media_token") or "")
    if not call_id or not raw_token:
        return JSONResponse(
            {"status": "error", "reason": "call_id_and_media_token_required"},
            status_code=400,
        )
    pending_call = await kernel.store.get_realtime_call(
        gateway.tenant_id, call_id
    )
    if not await _owns_call_channel(kernel, gateway, pending_call):
        # Keep a wrong channel, standby gateway and bad bearer
        # indistinguishable at this one-time secret boundary.
        return JSONResponse({"error": "media_token_refused"}, status_code=401)
    call = await kernel.store.claim_realtime_call_media(
        gateway.tenant_id,
        call_id,
        list((gateway.extra or {}).get("channels") or []),
        token_digest(raw_token),
    )
    if call is None:
        return JSONResponse({"error": "media_token_refused"}, status_code=401)
    context = call.tool_context or {}
    tool_token = kernel.mcp.issue_run_token(
        call.tenant_id,
        GrantSet.of(list(context.get("allow") or []), list(context.get("deny") or [])),
        run_id=call.run_id,
        actor=call.owner_id,
        workspace_id=context.get("workspace_id"),
        on_behalf_of=context.get("on_behalf_of") or call.owner_id,
        extra={
            "realtime_call": call.id,
            "principal_role": str(context.get("role") or ""),
            "principal_scope": dict(context.get("scope") or {}),
        },
        ttl_seconds=kernel.mcp.MAX_RUN_TOKEN_TTL_SECONDS,
    )
    await kernel.store.append_realtime_call_event(
        RealtimeCallEvent(
            id=f"callev_{uuid.uuid4().hex}",
            tenant_id=call.tenant_id,
            call_id=call.id,
            type="participant_joined",
            participant_id=call.owner_id,
            payload={"label": "You", "kind": "user"},
        )
    )
    return JSONResponse({
        "status": "ok",
        "call": call_view(call),
        "channel_id": call.channel_id,
        "tool_token": tool_token,
        "session_profile": dict((call.tool_context or {}).get("provider_route") or {}),
    })


async def append_call_event(
    call_id: str, body: dict, request: Request, kernel
) -> JSONResponse:
    gateway = _gateway_token(request, kernel)
    if gateway is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    call = await kernel.store.get_realtime_call(gateway.tenant_id, call_id)
    if (
        not await _owns_call_channel(kernel, gateway, call)
        or call.status == "ended"
    ):
        return JSONResponse({"error": "call_not_active"}, status_code=409)
    event_type = str(body.get("type") or "")
    if event_type not in CALL_EVENT_TYPES:
        return JSONResponse({"status": "error", "reason": "bad_event_type"}, status_code=400)
    payload = safe_gateway_payload(event_type, body.get("payload"))
    if payload is None:
        return JSONResponse(
            {"status": "error", "reason": "unsafe_event_payload"}, status_code=400
        )
    if event_type == "hitl" and (
        payload.get("status") != "pending" or not payload.get("request_id")
    ):
        return JSONResponse(
            {"status": "error", "reason": "gateway_hitl_must_be_pending"},
            status_code=400,
        )
    event = RealtimeCallEvent(
        id=str(body.get("id") or f"callev_{uuid.uuid4().hex}"),
        tenant_id=gateway.tenant_id,
        call_id=call_id,
        type=event_type,
        participant_id=(
            str(body["participant_id"])[:200]
            if body.get("participant_id") is not None
            else None
        ),
        payload=payload,
    )
    await kernel.store.append_realtime_call_event(event)
    await project_call_transcript(kernel, call, event)
    if event_type == "hitl":
        observed = await kernel.store.get_realtime_call_hitl_event(
            gateway.tenant_id, call_id, str(payload["request_id"])
        )
        next_status = (
            "held"
            if observed is not None and observed.payload.get("status") == "pending"
            else "active"
        )
        call = replace(call, status=next_status, updated_at=utcnow())
        await kernel.store.update_realtime_call(call)
    return JSONResponse({"status": "ok", "event": event_view(event)})


async def get_call_hitl(
    call_id: str, request_id: str, request: Request, kernel
) -> JSONResponse:
    gateway = _gateway_token(request, kernel)
    if gateway is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    call = await kernel.store.get_realtime_call(gateway.tenant_id, call_id)
    if not await _owns_call_channel(kernel, gateway, call):
        return JSONResponse({"error": "call_not_found"}, status_code=404)
    event = await kernel.store.get_realtime_call_hitl_event(
        gateway.tenant_id, call_id, request_id
    )
    if event is None:
        return JSONResponse({
            "status": "pending",
            "request_id": request_id,
        })
    return JSONResponse({
        "status": str(event.payload.get("status") or "pending"),
        "request_id": request_id,
        "event": event_view(event),
    })


async def set_call_state(
    call_id: str, body: dict, request: Request, kernel
) -> JSONResponse:
    gateway = _gateway_token(request, kernel)
    if gateway is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    call = await kernel.store.get_realtime_call(gateway.tenant_id, call_id)
    if not await _owns_call_channel(kernel, gateway, call):
        return JSONResponse({"error": "call_not_found"}, status_code=404)
    requested = str(body.get("status") or "")
    if requested not in {"active", "reconnecting", "failed"} or call.status == "ended":
        return JSONResponse({"status": "error", "reason": "bad_transition"}, status_code=409)
    call = replace(call, status=requested, updated_at=utcnow())
    await kernel.store.update_realtime_call(call)
    return JSONResponse({"status": "ok", "call": call_view(call)})


def _claim_endpoint(kernel_dep):
    async def endpoint(body: dict, request: Request, k=kernel_dep):
        return await claim_call_media(body, request, k)
    return endpoint


def _call_body_endpoint(handler, kernel_dep):
    async def endpoint(call_id: str, body: dict, request: Request, k=kernel_dep):
        return await handler(call_id, body, request, k)
    return endpoint


def _call_hitl_endpoint(kernel_dep):
    async def endpoint(call_id: str, request_id: str, request: Request, k=kernel_dep):
        return await get_call_hitl(call_id, request_id, request, k)
    return endpoint


def register_gateway_call_routes(app, *, get_kernel) -> None:
    kernel_dep = Depends(get_kernel)
    app.add_api_route(
        "/v1/calls/gateway/claim", _claim_endpoint(kernel_dep),
        methods=["POST"], name="claim_realtime_call_media",
    )
    app.add_api_route(
        "/v1/calls/gateway/{call_id}/events",
        _call_body_endpoint(append_call_event, kernel_dep),
        methods=["POST"], name="append_realtime_call_event",
    )
    app.add_api_route(
        "/v1/calls/gateway/{call_id}/state",
        _call_body_endpoint(set_call_state, kernel_dep),
        methods=["POST"], name="set_realtime_call_state",
    )
    app.add_api_route(
        "/v1/calls/gateway/{call_id}/hitl/{request_id}",
        _call_hitl_endpoint(kernel_dep),
        methods=["GET"], name="get_realtime_call_hitl",
    )
