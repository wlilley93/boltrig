"""Durable single-owner reconciliation and observation links."""

from __future__ import annotations

import re

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from boltrig.models import ChannelGatewayStatus, utcnow

from .channel_gateway_auth import gateway_run_token
from .channel_gateway_specs import (
    GATEWAY_OWNER_LEASE_SECONDS,
    OBSERVED_STATES,
    channel_desired_revision,
    resolved_gateway_spec,
)


async def reconcile_gateway(request: Request, kernel) -> JSONResponse:
    token = gateway_run_token(request, kernel)
    if token is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    gateway_id = str(token.extra.get("gateway_id") or "channel-gateway")
    specs = []
    for channel_id in list(token.extra.get("channels") or []):
        channel = await kernel.store.get_channel(token.tenant_id, channel_id)
        if channel is None or not channel.enabled or channel.transport != "socket":
            continue
        lease = await kernel.store.claim_channel_gateway_lease(
            token.tenant_id,
            channel_id,
            gateway_id,
            token.lease_id,
            GATEWAY_OWNER_LEASE_SECONDS,
        )
        if lease is None:
            specs.append(await _standby_spec(kernel, channel))
            continue
        spec = await resolved_gateway_spec(kernel, channel)
        spec["ownership"] = {
            "status": "owner",
            "lease_expires_at": lease.lease_expires_at.isoformat(),
            "lease_seconds": GATEWAY_OWNER_LEASE_SECONDS,
            "owner_lease_id_disclosed": False,
        }
        specs.append(spec)
    return JSONResponse(
        {
            "gateway_id": gateway_id,
            "channels": specs,
            "scope": list(token.extra.get("channels") or []),
            "owner_lease_seconds": GATEWAY_OWNER_LEASE_SECONDS,
        }
    )


async def _standby_spec(kernel, channel) -> dict:
    credential_row = (
        await kernel.store.get_credential_ref(
            channel.tenant_id, channel.credential_ref
        )
        if channel.credential_ref
        else None
    )
    return {
        "channel_id": channel.id,
        "platform": channel.platform,
        "revision": channel_desired_revision(channel, credential_row),
        "state": "standby",
        "reason_code": "gateway_owner_lease_held",
        "provider_credentials_included": False,
    }


async def record_gateway_heartbeat(
    body: dict, request: Request, kernel
) -> JSONResponse:
    token = gateway_run_token(request, kernel)
    if token is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    allowed = set(token.extra.get("channels") or [])
    observations = body.get("observations") or []
    if not isinstance(observations, list) or len(observations) > len(allowed):
        return JSONResponse(
            {"status": "error", "reason": "invalid observations"},
            status_code=400,
        )
    accepted = fenced = 0
    for observation in observations:
        outcome = await _record_observation(
            kernel, token, allowed, observation
        )
        accepted += outcome == "accepted"
        fenced += outcome == "fenced"
    return JSONResponse(
        {"status": "ok", "accepted": accepted, "fenced": fenced}
    )


async def _record_observation(kernel, token, allowed: set, observation) -> str:
    parsed = _parse_observation(allowed, observation)
    if parsed is None:
        return "ignored"
    channel_id, state, observed_revision, reason_code = parsed
    channel = await kernel.store.get_channel(token.tenant_id, channel_id)
    if channel is None:
        return "ignored"
    if not await kernel.store.channel_gateway_lease_owned(
        token.tenant_id, channel_id, token.lease_id
    ):
        return "fenced"
    credential_row = (
        await kernel.store.get_credential_ref(
            token.tenant_id, channel.credential_ref
        )
        if channel.credential_ref
        else None
    )
    await kernel.store.upsert_channel_gateway_status(
        ChannelGatewayStatus(
            tenant_id=token.tenant_id,
            channel_id=channel_id,
            gateway_id=str(token.extra.get("gateway_id") or "channel-gateway"),
            desired_revision=channel_desired_revision(channel, credential_row),
            observed_revision=observed_revision,
            status=state,
            reason_code=reason_code,
            observed_at=utcnow(),
        )
    )
    return "accepted"


def _parse_observation(allowed: set, observation):
    if not isinstance(observation, dict):
        return None
    channel_id = str(observation.get("channel_id") or "")
    state = str(observation.get("status") or "")
    revision = str(observation.get("revision") or "")
    reason = str(observation.get("reason_code") or "") or None
    if (
        channel_id not in allowed
        or state not in OBSERVED_STATES
        or not re.fullmatch(r"[a-f0-9]{64}", revision)
        or (
            reason is not None
            and not re.fullmatch(r"[a-z0-9_:-]{1,80}", reason)
        )
    ):
        return None
    return channel_id, state, revision, reason


def register_gateway_reconcile_routes(app, *, get_kernel) -> None:
    kernel = Depends(get_kernel)

    async def reconcile_endpoint(request: Request, k=kernel):
        return await reconcile_gateway(request, k)

    async def heartbeat_endpoint(body: dict, request: Request, k=kernel):
        return await record_gateway_heartbeat(body, request, k)

    app.add_api_route(
        "/v1/channels/gateway/reconcile",
        reconcile_endpoint,
        methods=["GET"],
        name="gateway_reconcile",
    )
    app.add_api_route(
        "/v1/channels/gateway/heartbeat",
        heartbeat_endpoint,
        methods=["POST"],
        name="gateway_heartbeat",
    )


__all__ = ["register_gateway_reconcile_routes"]
