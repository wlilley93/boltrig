"""Lease-fenced durable outbox links for the elected gateway owner."""

from __future__ import annotations

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from .channel_gateway_auth import gateway_run_token


MAX_CLAIM_BATCH = 50
MAX_LEASE_SECONDS = 300
OUTBOX_MAX_ATTEMPTS = 8
OUTBOX_BACKOFF_SECONDS = 5


async def claim_gateway_outbox(
    body: dict, request: Request, kernel
) -> JSONResponse:
    token = gateway_run_token(request, kernel)
    if token is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        limit = max(
            1, min(int(body.get("limit") or 10), MAX_CLAIM_BATCH)
        )
        lease = max(
            1,
            min(
                int(body.get("lease_seconds") or 30),
                MAX_LEASE_SECONDS,
            ),
        )
    except (TypeError, ValueError):
        return JSONResponse(
            {"status": "error", "reason": "bad limit/lease"},
            status_code=400,
        )
    active_channels = await _owned_channels(kernel, token, lease)
    claimed = await kernel.store.claim_channel_outbox(
        token.tenant_id,
        active_channels,
        token.lease_id,
        lease,
        limit,
    )
    return JSONResponse(
        {
            "messages": [
                {
                    "id": message.id,
                    "channel_id": message.channel_id,
                    "payload": message.payload,
                    "attempts": message.attempts,
                }
                for message in claimed
            ]
        }
    )


async def _owned_channels(kernel, token, outbox_lease: int) -> list[str]:
    active = []
    for channel_id in list(token.extra.get("channels") or []):
        channel = await kernel.store.get_channel(token.tenant_id, channel_id)
        owns = await kernel.store.channel_gateway_lease_owned(
            token.tenant_id,
            channel_id,
            token.lease_id,
            minimum_remaining_seconds=outbox_lease,
        )
        if (
            channel is not None
            and channel.enabled
            and channel.transport == "socket"
            and owns
        ):
            active.append(channel_id)
    return active


async def ack_gateway_outbox(
    message_id: str, request: Request, kernel
) -> JSONResponse:
    token = gateway_run_token(request, kernel)
    if token is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    accepted = await kernel.store.ack_channel_outbox(
        token.tenant_id, message_id, token.lease_id
    )
    return JSONResponse(
        {"status": "ok" if accepted else "not_claimed"},
        status_code=200 if accepted else 409,
    )


async def fail_gateway_outbox(
    message_id: str, body: dict, request: Request, kernel
) -> JSONResponse:
    token = gateway_run_token(request, kernel)
    if token is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    accepted = await kernel.store.fail_channel_outbox(
        token.tenant_id,
        message_id,
        token.lease_id,
        str(body.get("error") or "delivery failed"),
        max_attempts=OUTBOX_MAX_ATTEMPTS,
        backoff_seconds=OUTBOX_BACKOFF_SECONDS,
    )
    return JSONResponse(
        {"status": "ok" if accepted else "not_claimed"},
        status_code=200 if accepted else 409,
    )


def register_gateway_outbox_routes(app, *, get_kernel) -> None:
    kernel = Depends(get_kernel)

    async def claim_endpoint(body: dict, request: Request, k=kernel):
        return await claim_gateway_outbox(body, request, k)

    async def ack_endpoint(message_id: str, request: Request, k=kernel):
        return await ack_gateway_outbox(message_id, request, k)

    async def fail_endpoint(
        message_id: str, body: dict, request: Request, k=kernel
    ):
        return await fail_gateway_outbox(message_id, body, request, k)

    app.add_api_route(
        "/v1/channels/gateway/outbox/claim",
        claim_endpoint,
        methods=["POST"],
        name="gateway_outbox_claim",
    )
    app.add_api_route(
        "/v1/channels/gateway/outbox/{message_id}/ack",
        ack_endpoint,
        methods=["POST"],
        name="gateway_outbox_ack",
    )
    app.add_api_route(
        "/v1/channels/gateway/outbox/{message_id}/fail",
        fail_endpoint,
        methods=["POST"],
        name="gateway_outbox_fail",
    )


__all__ = ["register_gateway_outbox_routes"]
