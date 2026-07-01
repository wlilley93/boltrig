"""Channel HTTP surface (decision 0003, Phase 1: the webhook / request-response
class in-kernel).

Two kinds of route:
  - Management (admin-gated, authenticated by the normal principal): list the
    tenant's channels. connect/configure/disconnect land with the console beat
    (they need a kernel-side credential write).
  - Ingress (NO principal - authenticated by the channel's own signature): a
    signed inbound webhook. The tenant is resolved from the verified channel, the
    sender from a tenant-scoped binding, and the message becomes a governed
    work-item intake. The identical terminal seam every channel shares:
        verify -> sender->Principal -> normalise(tenant from binding) -> intake.
"""

from __future__ import annotations

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from boltrig.adapters.builtin.inbound_webhook import (
    WebhookAuthError,
    WebhookValidationError,
    verify_and_normalise,
)
from boltrig.models import ActionType, AuditEvent, utcnow
from boltrig.work.normalise import normalise

from .channel_gateway import resolve_channel_principal


def register_channel_routes(app, *, principal_dep, get_kernel) -> None:
    from boltrig.identity.rbac import can_author

    P = Depends(principal_dep)
    K = Depends(get_kernel)

    @app.get("/v1/channels")
    async def list_channels(k=K, p=P) -> JSONResponse:
        if not can_author(p.role):
            return JSONResponse({"status": "denied", "reason": "admin only"}, status_code=403)
        chans = await k.store.list_channels(p.tenant_id)
        return JSONResponse(
            {
                "channels": [
                    {
                        "id": c.id, "platform": c.platform, "name": c.name,
                        "transport": c.transport, "enabled": c.enabled,
                        "unpaired_behavior": c.unpaired_behavior,
                    }
                    for c in chans
                ]
            }
        )

    @app.post("/v1/channels/{channel_id}/inbound")
    async def channel_inbound(channel_id: str, body: dict, request: Request, k=K) -> JSONResponse:
        # 1. resolve the channel by its unguessable id (tenant comes from HERE)
        ch = await k.store.get_channel_by_id(channel_id)
        if ch is None or not ch.enabled or ch.transport != "webhook":
            return JSONResponse({"error": "unknown_channel"}, status_code=404)

        # 2. resolve the signing secret kernel-side (SEC-05), never from the body
        secret = None
        if ch.credential_ref:
            ref = await k.store.get_credential_ref(ch.tenant_id, ch.credential_ref)
            secret = (ref or {}).get("secret")

        # 3. verify the signature at the edge, before acting on the body
        try:
            verify_and_normalise(body, dict(request.headers), secret)
        except WebhookAuthError:
            return JSONResponse({"status": "denied", "reason": "signature"}, status_code=401)
        except WebhookValidationError as exc:
            return JSONResponse({"status": "error", "reason": str(exc)}, status_code=400)

        # 4. bind the tenant from the VERIFIED channel (RLS + K-3)
        from boltrig.store.postgres import set_current_tenant

        set_current_tenant(ch.tenant_id)

        # 5. map the verified sender -> a governed Principal (kernel-authoritative)
        sender_field = ch.config.get("sender_field", "sender")
        external_user_id = str(body.get(sender_field) or "").strip()
        if not external_user_id:
            return JSONResponse({"status": "error", "reason": "no sender"}, status_code=400)
        principal = await resolve_channel_principal(k.store, ch, external_user_id)
        if principal is None:
            # unpaired sender -> the channel's configured behaviour (fail-closed default)
            if ch.unpaired_behavior == "ignore":
                return JSONResponse({"status": "ignored"}, status_code=200)
            return JSONResponse(
                {"status": "denied", "reason": "sender not paired"}, status_code=403
            )

        # 6. normalise -> a work-item intake (the CoS routes it), tenant-scoped
        item = normalise(body, source=ch.platform, tenant_id=ch.tenant_id)
        item.on_behalf_of = principal.subject
        await k.store.create_work_item(item)

        # 7. audit the intake as the resolved principal (audit-always)
        await k.audit.write(
            AuditEvent(
                tenant_id=ch.tenant_id, ts=utcnow(), actor=principal.subject,
                actor_tier="human", action_type=ActionType.TOOL_CALL, noun="channel",
                verb="channel.inbound", status="ok",
                detail={"channel": ch.id, "work_item": item.id, "platform": ch.platform},
            )
        )
        return JSONResponse({"status": "ok", "work_item": item.id}, status_code=202)
