"""Author-gated, show-once channel-gateway session issuance."""

from __future__ import annotations

import re

from fastapi import Depends
from fastapi.responses import JSONResponse

from boltrig.identity.rbac import can_author
from boltrig.models import ActionType, AuditEvent, GrantSet, utcnow


async def issue_gateway_session(body: dict, kernel, principal) -> JSONResponse:
    if not can_author(principal.role):
        return JSONResponse(
            {"status": "denied", "reason": "admin only"}, status_code=403
        )
    channel_ids = sorted(
        {
            str(channel_id).strip()
            for channel_id in (body.get("channels") or [])
            if str(channel_id).strip()
        }
    )
    if not channel_ids:
        return JSONResponse(
            {"status": "error", "reason": "channels (a non-empty id list) required"},
            status_code=400,
        )
    gateway_id = str(body.get("gateway_id") or "channel-gateway").strip()
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", gateway_id):
        return JSONResponse(
            {"status": "error", "reason": "gateway_id is invalid"},
            status_code=400,
        )
    if not await _channels_are_eligible(kernel, principal.tenant_id, channel_ids):
        return JSONResponse(
            {
                "status": "error",
                "reason": "every channel must be an enabled socket-class channel",
            },
            status_code=400,
        )
    try:
        ttl = int(
            body.get("ttl_seconds") or kernel.mcp.MAX_RUN_TOKEN_TTL_SECONDS
        )
        token = kernel.mcp.issue_run_token(
            principal.tenant_id,
            GrantSet(),
            actor="channel-gateway",
            extra={
                "channel_gateway": True,
                "channels": channel_ids,
                "gateway_id": gateway_id,
            },
            ttl_seconds=ttl,
        )
    except (TypeError, ValueError) as exc:
        return JSONResponse(
            {"status": "error", "reason": str(exc)}, status_code=400
        )
    await _audit_session(
        kernel, principal, channel_ids, gateway_id, ttl
    )
    return JSONResponse(
        {
            "status": "ok",
            "token": token,
            "channels": channel_ids,
            "gateway_id": gateway_id,
            "expires_in": ttl,
            "bootstrap": {
                "token_delivery": "show_once",
                "recovery": "replace_token_file_or_restart",
                "owner_election": "durable_per_channel_lease",
                "provider_credentials_included": False,
            },
        },
        status_code=201,
    )


async def _channels_are_eligible(kernel, tenant_id: str, channel_ids: list[str]) -> bool:
    for channel_id in channel_ids:
        channel = await kernel.store.get_channel(tenant_id, channel_id)
        if channel is None or not channel.enabled or channel.transport != "socket":
            return False
    return True


async def _audit_session(kernel, principal, channel_ids, gateway_id, ttl) -> None:
    await kernel.audit.write(
        AuditEvent(
            tenant_id=principal.tenant_id,
            ts=utcnow(),
            actor=principal.subject,
            actor_tier=principal.actor_tier,
            action_type=ActionType.TOOL_CALL,
            noun="channel",
            verb="channel.gateway.session",
            status="ok",
            on_behalf_of=principal.on_behalf_of,
            detail={
                "channels": channel_ids,
                "gateway_id": gateway_id,
                "ttl_seconds": ttl,
            },
        )
    )


def register_gateway_session_route(
    app, *, principal_dep, get_kernel
) -> None:
    principal = Depends(principal_dep)
    kernel = Depends(get_kernel)

    async def endpoint(body: dict, k=kernel, p=principal):
        return await issue_gateway_session(body, k, p)

    app.add_api_route(
        "/v1/channels/gateway/session",
        endpoint,
        methods=["POST"],
        name="gateway_session",
    )


__all__ = ["register_gateway_session_route"]
