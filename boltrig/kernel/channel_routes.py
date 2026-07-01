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

import hashlib
import secrets
import uuid
from datetime import timedelta

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from boltrig.adapters.builtin.inbound_webhook import (
    WebhookAuthError,
    WebhookValidationError,
    verify_and_normalise,
)
from boltrig.models import (
    ActionType,
    AuditEvent,
    Channel,
    ChannelBinding,
    ChannelPairing,
    utcnow,
)
from boltrig.models.channels import transport_for
from boltrig.work.normalise import normalise

from .channel_gateway import CHANNEL_TIERS, resolve_channel_principal

# The pairing flow (decision 0003): one-time codes are short, human-transcribable,
# hashed at rest (SEC-05), TTL-bounded, lockout-guarded. They bind an unknown
# external sender to an internal identity; consumption is single-use.
PAIR_TTL_MINUTES = 15
PAIR_MAX_TTL_MINUTES = 60
PAIR_MAX_ATTEMPTS = 5


def _hash_code(code: str) -> str:
    """The at-rest representation of a pairing code: sha256, never plaintext."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _gen_pairing_code() -> str:
    # 8 url-safe chars -> ~47 bits, fine for a short-lived, rate-limited, hashed code.
    return secrets.token_urlsafe(6)[:8].upper()


async def _audit(kernel, p, verb: str, detail: dict, status: str = "ok") -> None:
    await kernel.audit.write(
        AuditEvent(
            tenant_id=p.tenant_id, ts=utcnow(), actor=p.subject, actor_tier=p.actor_tier,
            action_type=ActionType.TOOL_CALL, noun="channel", verb=verb, status=status,
            on_behalf_of=p.on_behalf_of, detail=detail,
        )
    )


async def _consume_pairing(kernel, channel, external_user_id, code) -> bool:
    """Consume a one-time pairing code for an unbound sender (decision 0003).

    Enforces the full pairing contract: TTL expiry, wrong-code lockout (attempts
    cap -> expired), and single-use consume. On a successful consume it mints the
    binding the pairing authorised. Returns True if the sender is now bound."""
    pairing = await kernel.store.get_pending_pairing_for_sender(
        channel.tenant_id, channel.id, external_user_id
    )
    if pairing is None:
        return False  # no pending pairing for this sender
    if pairing.expires_at is not None and pairing.expires_at <= utcnow():
        return False  # expired (TTL or lockout)
    if _hash_code(code) != pairing.code_hash:
        # wrong code -> bump attempts; lockout flips status to 'expired' at the cap.
        await kernel.store.bump_channel_pairing_attempts(
            channel.tenant_id, pairing.id, cap=PAIR_MAX_ATTEMPTS
        )
        return False
    if not await kernel.store.consume_channel_pairing(channel.tenant_id, pairing.id):
        return False  # raced / already consumed (single-use CAS)
    binding = ChannelBinding(
        id=f"cb_{uuid.uuid4().hex[:12]}", tenant_id=channel.tenant_id,
        channel_id=channel.id, platform=channel.platform,
        external_user_id=external_user_id, subject=pairing.subject, role=pairing.role,
    )
    await kernel.store.upsert_channel_binding(binding)
    await kernel.audit.write(
        AuditEvent(
            tenant_id=channel.tenant_id, ts=utcnow(), actor=pairing.subject,
            actor_tier="human", action_type=ActionType.TOOL_CALL, noun="channel",
            verb="channel.pair.consume", status="ok",
            detail={"channel": channel.id, "external_user_id": external_user_id,
                    "subject": pairing.subject, "pairing": pairing.id},
        )
    )
    return True


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
            # unpaired sender. If the channel is in 'pair' mode and the message
            # carries a pairing code, consume it (expiry + wrong-code lockout) and
            # bind the sender, then proceed as the now-bound principal. Otherwise
            # apply the channel's configured behaviour (fail-closed default).
            if ch.unpaired_behavior == "pair":
                code = str(body.get("pairing_code") or "").strip()
                if code and await _consume_pairing(k, ch, external_user_id, code):
                    principal = await resolve_channel_principal(
                        k.store, ch, external_user_id
                    )
            if principal is None:
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

    # === Governance verbs (decision 0003): admin-authored channel lifecycle. ===
    # connect/configure/disconnect mutate the governed Channel noun; pair/bindings
    # map verified external senders to internal identities. All admin-gated +
    # audited. connect writes the signing secret kernel-side (SEC-04/05); the
    # credential never crosses the boundary or reaches an agent.

    def _admin(p) -> JSONResponse | None:
        from boltrig.identity.rbac import can_author

        return None if can_author(p.role) else JSONResponse(
            {"status": "denied", "reason": "admin only"}, status_code=403
        )

    @app.post("/v1/channels")
    async def channel_connect(body: dict, k=K, p=P) -> JSONResponse:
        denied = _admin(p)
        if denied:
            return denied
        platform = str(body.get("platform") or "").strip()
        name = str(body.get("name") or "").strip()
        if platform not in ("webhook", "msteams") or not name:
            return JSONResponse(
                {"status": "error", "reason": "platform must be a webhook-class + name"},
                status_code=400,
            )
        channel_id = f"ch_{uuid.uuid4().hex[:16]}"
        secret = str(body.get("signing_secret") or "").strip()
        credential_ref = None
        if secret:
            credential_ref = f"cred_{uuid.uuid4().hex[:16]}"
            await k.store.set_credential_ref(p.tenant_id, credential_ref, {"secret": secret})
        channel = Channel(
            id=channel_id, tenant_id=p.tenant_id, platform=platform, name=name,
            transport=transport_for(platform), credential_ref=credential_ref,
            config=body.get("config") or {}, enabled=bool(body.get("enabled", True)),
            unpaired_behavior=str(body.get("unpaired_behavior") or "reject"),
        )
        await k.store.upsert_channel(channel)
        await _audit(k, p, "channel.connect",
                     {"channel": channel_id, "platform": platform, "transport": channel.transport})
        return JSONResponse(
            {"status": "ok", "channel": channel_id,
             "inbound_url": f"/v1/channels/{channel_id}/inbound"},
            status_code=201,
        )

    @app.patch("/v1/channels/{channel_id}")
    async def channel_configure(channel_id: str, body: dict, k=K, p=P) -> JSONResponse:
        denied = _admin(p)
        if denied:
            return denied
        ch = await k.store.get_channel(p.tenant_id, channel_id)
        if ch is None:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        if "name" in body:
            ch.name = str(body["name"])
        if "config" in body and isinstance(body["config"], dict):
            ch.config = body["config"]
        if "unpaired_behavior" in body:
            ch.unpaired_behavior = str(body["unpaired_behavior"])
        if "enabled" in body:
            ch.enabled = bool(body["enabled"])
        await k.store.upsert_channel(ch)
        await _audit(k, p, "channel.configure", {"channel": channel_id})
        return JSONResponse({"status": "ok"})

    @app.delete("/v1/channels/{channel_id}")
    async def channel_disconnect(channel_id: str, k=K, p=P) -> JSONResponse:
        denied = _admin(p)
        if denied:
            return denied
        ch = await k.store.get_channel(p.tenant_id, channel_id)
        if ch is None:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        await k.store.delete_channel(p.tenant_id, channel_id)
        await _audit(k, p, "channel.disconnect", {"channel": channel_id}, status="ok")
        return JSONResponse({"status": "ok"})

    @app.post("/v1/channels/{channel_id}/pair")
    async def channel_pair(channel_id: str, body: dict, k=K, p=P) -> JSONResponse:
        # HITL-gated by being admin-only: an admin author issuing the code IS the
        # human authorising the bind (decision 0003). The code is shown ONCE.
        denied = _admin(p)
        if denied:
            return denied
        ch = await k.store.get_channel(p.tenant_id, channel_id)
        if ch is None:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        external_user_id = str(body.get("external_user_id") or "").strip()
        subject = str(body.get("subject") or "").strip()
        role = str(body.get("role") or "member").strip()
        if not external_user_id or not subject or role not in CHANNEL_TIERS:
            return JSONResponse(
                {"status": "error", "reason": "external_user_id + subject + valid role required"},
                status_code=400,
            )
        try:
            ttl = int(body.get("ttl_minutes") or PAIR_TTL_MINUTES)
        except (TypeError, ValueError):
            ttl = PAIR_TTL_MINUTES
        ttl = max(1, min(ttl, PAIR_MAX_TTL_MINUTES))
        code = _gen_pairing_code()
        now = utcnow()
        pairing = ChannelPairing(
            id=f"cp_{uuid.uuid4().hex[:16]}", tenant_id=p.tenant_id, channel_id=channel_id,
            code_hash=_hash_code(code), external_user_id=external_user_id,
            subject=subject, role=role,
            status="pending", attempts=0, expires_at=now + timedelta(minutes=ttl),
            created_at=now,
        )
        await k.store.create_channel_pairing(pairing)
        await _audit(k, p, "channel.pair",
                     {"channel": channel_id, "external_user_id": external_user_id,
                      "subject": subject, "role": role, "pairing": pairing.id})
        return JSONResponse({"status": "ok", "pairing_id": pairing.id, "code": code},
                            status_code=201)  # code returned ONCE, never again

    @app.post("/v1/channels/{channel_id}/bindings")
    async def channel_bind(channel_id: str, body: dict, k=K, p=P) -> JSONResponse:
        # Direct admin binding (skip the code) - the admin vouches for the mapping.
        denied = _admin(p)
        if denied:
            return denied
        ch = await k.store.get_channel(p.tenant_id, channel_id)
        if ch is None:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        external_user_id = str(body.get("external_user_id") or "").strip()
        subject = str(body.get("subject") or "").strip()
        role = str(body.get("role") or "member").strip()
        if not external_user_id or not subject or role not in CHANNEL_TIERS:
            return JSONResponse(
                {"status": "error", "reason": "external_user_id + subject + valid role required"},
                status_code=400,
            )
        binding = ChannelBinding(
            id=f"cb_{uuid.uuid4().hex[:12]}", tenant_id=p.tenant_id, channel_id=channel_id,
            platform=ch.platform, external_user_id=external_user_id,
            subject=subject, role=role,
        )
        await k.store.upsert_channel_binding(binding)
        await _audit(k, p, "channel.bind",
                     {"channel": channel_id, "external_user_id": external_user_id,
                      "subject": subject, "role": role, "binding": binding.id})
        return JSONResponse({"status": "ok", "binding": binding.id}, status_code=201)

    @app.get("/v1/channels/{channel_id}/bindings")
    async def list_bindings(channel_id: str, k=K, p=P) -> JSONResponse:
        denied = _admin(p)
        if denied:
            return denied
        rows = await k.store.list_channel_bindings(p.tenant_id, channel_id)
        return JSONResponse({"bindings": [
            {"id": b.id, "external_user_id": b.external_user_id, "subject": b.subject,
             "role": b.role}
            for b in rows
        ]})

    @app.delete("/v1/channels/{channel_id}/bindings/{binding_id}")
    async def delete_binding(channel_id: str, binding_id: str, k=K, p=P) -> JSONResponse:
        denied = _admin(p)
        if denied:
            return denied
        # the path channel_id is authoritative: the binding must belong to this
        # channel (else a wrong-but-tenant-valid id would delete across channels).
        rows = await k.store.list_channel_bindings(p.tenant_id, channel_id)
        if not any(b.id == binding_id for b in rows):
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        await k.store.delete_channel_binding(p.tenant_id, binding_id)
        await _audit(k, p, "channel.unbind", {"channel": channel_id, "binding": binding_id})
        return JSONResponse({"status": "ok"})
