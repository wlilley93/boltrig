"""Channel gateway links (decision 0003, Phase 2 skeleton).

The socket (persistent-connection) class is terminated by the severed
``services/channel_gateway`` daemon. That daemon owns no policy, no grants and
no persistent credential (condition 2): it re-enters the kernel over a
RUN-SCOPED token minted through the SAME seam the MCP face uses
(``McpFace.issue_run_token`` - hash-keyed, TTL-bound, revocable), and it talks
to its platforms with a connect-time secret injected at spawn (condition 7),
never stored here.

Three routes, two auth shapes:
  - ``POST /v1/channels/gateway/session`` - ADMIN-gated (the normal principal):
    mints the gateway's run-scoped token for an explicit set of the tenant's
    socket channels. The token is returned ONCE, audited, and never logged; the
    operator injects it into the gateway's environment at spawn (mirrors the
    pi_runtime model-key handling). TTL-bounded: when it lapses the gateway's
    links start refusing and a supervised respawn re-injects a fresh token.
  - ``POST /v1/channels/gateway/outbox/claim`` and ``.../outbox/{id}/ack|fail`` -
    token-gated (``x-boltrig-mcp-token``, the MCP header name): the durable
    outbound hand-off. The token's lease id IS the claim worker id, and its
    channel set bounds what may be claimed.

The INBOUND link has no route of its own by design: the gateway POSTs
normalized messages to ``/v1/channels/{id}/inbound`` signed with the same
connect-time HMAC secret the webhook class uses, so the kernel keeps ONE
intake path (see channel_routes.py).
"""

from __future__ import annotations

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from boltrig.models import ActionType, AuditEvent, GrantSet, utcnow

# Bounds on the outbox lease/pump knobs the gateway may ask for.
_MAX_CLAIM_BATCH = 50
_MAX_LEASE_SECONDS = 300
# Retry posture for a failed delivery: exponential backoff (base seconds),
# terminal 'failed' at the attempt cap so a poison message never hot-loops.
_OUTBOX_MAX_ATTEMPTS = 8
_OUTBOX_BACKOFF_SECONDS = 5

_SIDECAR_TOKEN_HEADER = "x-boltrig-mcp-token"


def register_channel_gateway_routes(app, *, principal_dep, get_kernel) -> None:
    from boltrig.identity.rbac import can_author

    P = Depends(principal_dep)
    K = Depends(get_kernel)

    def _gateway_token(request: Request, k):
        """Authenticate a gateway link call: a live run-scoped token minted for
        the channel gateway (extra.channel_gateway), else None (fail-closed)."""
        rt = k.mcp.lookup_run_token(request.headers.get(_SIDECAR_TOKEN_HEADER))
        if rt is None or not (rt.extra or {}).get("channel_gateway"):
            return None
        return rt

    @app.post("/v1/channels/gateway/session")
    async def gateway_session(body: dict, k=K, p=P) -> JSONResponse:
        # Admin-authored, audited, shown ONCE. The token carries no grants - it
        # authenticates the outbox links only; it can never invoke a verb.
        if not can_author(p.role):
            return JSONResponse({"status": "denied", "reason": "admin only"}, status_code=403)
        channel_ids = sorted({str(c).strip() for c in (body.get("channels") or []) if str(c).strip()})
        if not channel_ids:
            return JSONResponse(
                {"status": "error", "reason": "channels (a non-empty id list) required"},
                status_code=400,
            )
        for cid in channel_ids:
            ch = await k.store.get_channel(p.tenant_id, cid)
            if ch is None or not ch.enabled or ch.transport != "socket":
                return JSONResponse(
                    {"status": "error",
                     "reason": f"channel {cid} is not an enabled socket-class channel"},
                    status_code=400,
                )
        try:
            ttl = int(body.get("ttl_seconds") or k.mcp.MAX_RUN_TOKEN_TTL_SECONDS)
        except (TypeError, ValueError):
            ttl = k.mcp.MAX_RUN_TOKEN_TTL_SECONDS
        try:
            token = k.mcp.issue_run_token(
                p.tenant_id, GrantSet(),  # no verb authority - links only
                actor="channel-gateway",
                extra={"channel_gateway": True, "channels": channel_ids},
                ttl_seconds=ttl,
            )
        except ValueError as exc:
            return JSONResponse({"status": "error", "reason": str(exc)}, status_code=400)
        await k.audit.write(
            AuditEvent(
                tenant_id=p.tenant_id, ts=utcnow(), actor=p.subject, actor_tier=p.actor_tier,
                action_type=ActionType.TOOL_CALL, noun="channel", verb="channel.gateway.session",
                status="ok", on_behalf_of=p.on_behalf_of,
                detail={"channels": channel_ids, "ttl_seconds": ttl},
            )
        )
        # The token is returned exactly once here and is never logged; injection
        # into the gateway environment at spawn is the operator's connect-time act.
        return JSONResponse(
            {"status": "ok", "token": token, "channels": channel_ids, "expires_in": ttl},
            status_code=201,
        )

    @app.post("/v1/channels/gateway/outbox/claim")
    async def gateway_outbox_claim(body: dict, request: Request, k=K) -> JSONResponse:
        rt = _gateway_token(request, k)
        if rt is None:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            limit = max(1, min(int(body.get("limit") or 10), _MAX_CLAIM_BATCH))
            lease = max(1, min(int(body.get("lease_seconds") or 30), _MAX_LEASE_SECONDS))
        except (TypeError, ValueError):
            return JSONResponse({"status": "error", "reason": "bad limit/lease"}, status_code=400)
        # The token's channel set bounds the claim; the lease id is the worker id.
        claimed = await k.store.claim_channel_outbox(
            rt.tenant_id, list(rt.extra.get("channels") or []), rt.lease_id, lease, limit
        )
        return JSONResponse(
            {
                "messages": [
                    {
                        "id": m.id, "channel_id": m.channel_id, "payload": m.payload,
                        "attempts": m.attempts,
                    }
                    for m in claimed
                ]
            }
        )

    @app.post("/v1/channels/gateway/outbox/{message_id}/ack")
    async def gateway_outbox_ack(message_id: str, request: Request, k=K) -> JSONResponse:
        rt = _gateway_token(request, k)
        if rt is None:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if not await k.store.ack_channel_outbox(rt.tenant_id, message_id, rt.lease_id):
            # not claimed by THIS token (stale lease, already settled, or foreign)
            return JSONResponse({"status": "not_claimed"}, status_code=409)
        return JSONResponse({"status": "ok"})

    @app.post("/v1/channels/gateway/outbox/{message_id}/fail")
    async def gateway_outbox_fail(message_id: str, body: dict, request: Request, k=K) -> JSONResponse:
        rt = _gateway_token(request, k)
        if rt is None:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        error = str(body.get("error") or "delivery failed")
        if not await k.store.fail_channel_outbox(
            rt.tenant_id, message_id, rt.lease_id, error,
            max_attempts=_OUTBOX_MAX_ATTEMPTS, backoff_seconds=_OUTBOX_BACKOFF_SECONDS,
        ):
            return JSONResponse({"status": "not_claimed"}, status_code=409)
        return JSONResponse({"status": "ok"})
