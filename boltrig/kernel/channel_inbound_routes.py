"""The one signed intake path shared by webhook and socket channels."""

from __future__ import annotations

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from boltrig.adapters.builtin.inbound_webhook import (
    WebhookAuthError,
    WebhookValidationError,
    is_duplicate_delivery,
    verify_and_normalise,
)
from boltrig.models import (
    ActionType,
    AuditEvent,
    RateLimited,
    utcnow,
)
from boltrig.work.normalise import normalise

from .channel_principal import resolve_channel_principal
from .channel_workflow_trigger_bridge import bound_event_response


async def channel_inbound(
    channel_id: str, body: dict, request: Request, kernel
) -> JSONResponse:
    channel = await kernel.store.get_channel_by_id(channel_id)
    if (
        channel is None
        or not channel.enabled
        or channel.transport not in ("webhook", "socket")
    ):
        return JSONResponse({"error": "unknown_channel"}, status_code=404)
    candidate = await _verified_candidate(kernel, channel, body, request)
    if isinstance(candidate, JSONResponse):
        return candidate
    from boltrig.store.postgres import set_current_tenant

    set_current_tenant(channel.tenant_id)
    sender = str(
        body.get(channel.config.get("sender_field", "sender")) or ""
    ).strip()
    if not sender:
        return JSONResponse(
            {"status": "error", "reason": "no sender"}, status_code=400
        )
    principal = await _resolve_sender(kernel, channel, sender, body)
    if isinstance(principal, JSONResponse):
        return principal
    throttled = await _enforce_intake_rate(kernel, channel, sender)
    if throttled is not None:
        return throttled
    delivery = candidate.get("delivery_id")
    if delivery and await is_duplicate_delivery(
        kernel.store, channel.tenant_id, channel.id, str(delivery)
    ):
        return JSONResponse(
            {"status": "duplicate", "reason": "delivery already ingested"}
        )
    return await _terminal_or_work(
        kernel,
        channel,
        principal,
        sender,
        body,
        request,
        str(delivery or candidate["delivery_id"]),
    )


async def _verified_candidate(kernel, channel, body, request):
    from .channel_routes import _channel_secret

    credential = (
        await kernel.store.get_credential_ref(
            channel.tenant_id, channel.credential_ref
        )
        if channel.credential_ref
        else None
    )
    secret = await _channel_secret(kernel, credential)
    if not secret:
        return JSONResponse(
            {"error": "channel_misconfigured"}, status_code=503
        )
    try:
        return verify_and_normalise(body, dict(request.headers), secret)
    except WebhookAuthError:
        return JSONResponse(
            {"status": "denied", "reason": "signature"}, status_code=401
        )
    except WebhookValidationError as exc:
        return JSONResponse(
            {"status": "error", "reason": str(exc)}, status_code=400
        )


async def _resolve_sender(kernel, channel, sender: str, body: dict):
    from .channel_routes import _consume_pairing, _self_onboard

    principal = await resolve_channel_principal(
        kernel.store, channel, sender
    )
    if principal is None and channel.unpaired_behavior == "pair":
        code = str(body.get("pairing_code") or "").strip()
        if code and await _consume_pairing(kernel, channel, sender, code):
            principal = await resolve_channel_principal(
                kernel.store, channel, sender
            )
    if principal is None:
        try:
            principal = await _self_onboard(kernel, channel, sender)
        except RateLimited as exc:
            return _throttled("onboarding rate limit", exc)
    if principal is not None:
        return principal
    if channel.unpaired_behavior == "ignore":
        return JSONResponse({"status": "ignored"})
    return JSONResponse(
        {"status": "denied", "reason": "sender not paired"},
        status_code=403,
    )


async def _enforce_intake_rate(kernel, channel, sender: str):
    from .channel_routes import INBOUND_RL_PER_CHANNEL, INBOUND_RL_PER_SENDER

    try:
        await kernel.rate_limiter.enforce(
            channel.tenant_id,
            f"channel.inbound:{channel.id}",
            INBOUND_RL_PER_CHANNEL,
        )
        await kernel.rate_limiter.enforce(
            channel.tenant_id,
            f"channel.inbound:{channel.id}:{sender}",
            INBOUND_RL_PER_SENDER,
        )
    except RateLimited as exc:
        return _throttled("intake rate limit", exc)
    return None


def _throttled(reason: str, exc: RateLimited) -> JSONResponse:
    headers = {}
    if exc.retry_after_seconds is not None:
        headers["Retry-After"] = str(int(exc.retry_after_seconds))
    return JSONResponse(
        {"status": "throttled", "reason": reason},
        status_code=429,
        headers=headers,
    )


async def _terminal_or_work(
    kernel, channel, principal, sender, body, request, delivery: str
) -> JSONResponse:
    from .channel_routes import _hitl_reply_response, _resolve_addressing

    target, reply_route = _resolve_addressing(channel, body)
    terminal = await bound_event_response(
        _hitl_reply_response,
        kernel,
        channel,
        principal,
        sender,
        delivery,
        body,
        reply_route,
        request,
    )
    if terminal is not None:
        return terminal
    item = normalise(
        body, source=channel.platform, tenant_id=channel.tenant_id
    )
    item.on_behalf_of = principal.subject
    item.target, item.reply_route = target, reply_route
    item.reply_route["sender"] = sender
    await kernel.store.create_work_item(item)
    await _audit_intake(kernel, channel, principal, item)
    return JSONResponse(
        {"status": "ok", "work_item": item.id}, status_code=202
    )


async def _audit_intake(kernel, channel, principal, item) -> None:
    await kernel.audit.write(
        AuditEvent(
            tenant_id=channel.tenant_id,
            ts=utcnow(),
            actor=principal.subject,
            actor_tier="human",
            action_type=ActionType.TOOL_CALL,
            noun="channel",
            verb="channel.inbound",
            status="ok",
            detail={
                "channel": channel.id,
                "work_item": item.id,
                "platform": channel.platform,
                "target": item.target,
            },
        )
    )


def register_channel_inbound_route(app, *, get_kernel) -> None:
    kernel = Depends(get_kernel)

    async def endpoint(
        channel_id: str, body: dict, request: Request, k=kernel
    ):
        return await channel_inbound(channel_id, body, request, k)

    app.add_api_route(
        "/v1/channels/{channel_id}/inbound",
        endpoint,
        methods=["POST"],
        name="channel_inbound",
    )


__all__ = ["register_channel_inbound_route"]
