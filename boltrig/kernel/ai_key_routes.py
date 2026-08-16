"""Scoped AI-key routes with one-time secret intake."""

from __future__ import annotations

import hashlib
import json
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse

from boltrig.kernel.ai_key_proposal_routes import (
    activate_ai_key_config,
    proposal_audit,
    proposal_params,
    proposal_view,
    register_ai_key_proposal_routes,
)
from boltrig.kernel.control_routes import dispatch_control_route
from boltrig.models import AI_CONFIG_LEVELS, AI_CONFIG_MODALITIES, AiKeySecretProposal, utcnow
from boltrig.store.ai_key_proposals import AI_KEY_PROPOSAL_MAX_TTL


async def _authorize_ai_key(
    kernel,
    principal,
    level: str,
    scope_id: str,
    admin_roles: frozenset[str],
    workspace_admin_roles: frozenset[str],
):
    is_org_admin = principal.role in admin_roles
    if level == "org":
        if not is_org_admin:
            return _denied("org AI key requires org administration")
        return None
    org = await kernel.store.get_org(principal.tenant_id)
    if org is None or not org.allow_own_ai_keys:
        return _denied("organisation does not allow own AI keys")
    if level == "workspace" and not is_org_admin:
        member = await kernel.store.get_workspace_member(
            principal.tenant_id, scope_id, principal.subject
        )
        if member is None or member.role not in workspace_admin_roles:
            return _denied("must be a workspace owner/admin to set its AI key")
    elif level == "user" and not is_org_admin and scope_id != principal.subject:
        return _denied("may only set your own user AI key")
    return None


# Self-hosted providers whose servers authenticate nothing. The intake still
# requires secret material for the sealed-proposal path (digest + Bifrost
# provisioning both need a non-empty key), so an absent key is substituted with
# a fixed placeholder: it is the honest credential for a server that ignores
# the Authorization header, and it rides the same `seal_ref` sealed-proposal
# path as a real key (sealed, digested, unechoed; SEC-113 unchanged). Keyed
# providers are unaffected.
_KEYLESS_PROVIDERS = frozenset({"ollama"})
_KEYLESS_PLACEHOLDER = "keyless"


def _denied(reason):
    return JSONResponse({"status": "denied", "reason": reason}, status_code=403)


def _parse_ai_key_intake(body: dict, principal):
    if any(key in body for key in ("approval_id", "proposal_id", "secret_digest")):
        return None, _invalid("approval and proposal evidence is server-owned")
    level = str(body.get("level") or "").strip()
    if level not in AI_CONFIG_LEVELS:
        return None, _invalid(f"level must be one of {sorted(AI_CONFIG_LEVELS)}")
    default_scope = {"org": principal.tenant_id, "user": principal.subject}.get(level)
    scope_id = str(body.get("scope_id") or default_scope or "").strip()
    provider = str(body.get("provider") or "").strip()
    model = str(body.get("model") or "").strip()
    modality = str(body.get("modality") or "text").strip().lower()
    api_key = str(body.pop("api_key", None) or "").strip()
    base_url = str(body.get("base_url") or "").strip() or None
    if modality not in AI_CONFIG_MODALITIES:
        return None, _invalid("modality must be text or vision")
    if not scope_id or not provider or not model:
        return None, _invalid("scope_id, provider and model are required")
    if not api_key and provider not in _KEYLESS_PROVIDERS:
        return None, _invalid("an API key is required for this provider")
    if not api_key:
        api_key = _KEYLESS_PLACEHOLDER
    return (level, scope_id, provider, model, modality, api_key, base_url), None


def _invalid(reason):
    return JSONResponse({"status": "error", "reason": reason}, status_code=400)


def _new_proposal(principal, parsed):
    level, scope_id, provider, model, modality, api_key, base_url = parsed
    now = utcnow()
    proposal_id = f"akp_{uuid.uuid4().hex}"
    proposal = AiKeySecretProposal(
        id=proposal_id,
        tenant_id=principal.tenant_id,
        requested_by=principal.subject,
        requested_on_behalf_of=principal.on_behalf_of,
        workspace_id=principal.active_workspace_id,
        level=level,
        scope_id=scope_id,
        provider=provider,
        model=model,
        modality=modality,
        base_url=base_url,
        secret_ref=f"staged_ai_key:{proposal_id}",
        secret_digest=hashlib.sha256(api_key.encode("utf-8")).hexdigest(),
        created_at=now,
        expires_at=now + AI_KEY_PROPOSAL_MAX_TTL,
        updated_at=now,
    )
    return proposal, api_key


async def _dispatch_staged(kernel, principal, proposal, secret):
    # Store creation seals before persistence and atomically creates metadata.
    await kernel.store.create_ai_key_secret_proposal(proposal, secret)
    secret = ""
    try:
        return await dispatch_control_route(
            kernel,
            principal,
            "control.ai_key.set",
            proposal_params(proposal),
            request=None,
        )
    except Exception:
        await kernel.store.invalidate_ai_key_secret_proposal(
            principal.tenant_id,
            proposal.id,
            principal.subject,
            "invalidated",
            utcnow(),
        )
        raise


async def _bind_pending(kernel, principal, proposal, pending, audit):
    pending_body = json.loads(bytes(pending.body))
    approval_id = str(pending_body.get("hitl_request_id") or "")
    attached = (
        await kernel.store.attach_ai_key_proposal_approval(
            principal.tenant_id, proposal.id, principal.subject, approval_id
        )
        if approval_id
        else None
    )
    if attached is None:
        if approval_id:
            await kernel.store.expire_hitl(principal.tenant_id, approval_id)
        await kernel.store.invalidate_ai_key_secret_proposal(
            principal.tenant_id,
            proposal.id,
            principal.subject,
            "invalidated",
            utcnow(),
        )
        return JSONResponse(
            {
                "status": "unavailable",
                "reason": "sealed proposal could not be bound to approval",
            },
            status_code=503,
        )
    await audit(
        kernel,
        principal,
        "ai_key.proposal.create",
        proposal_audit(attached),
        status="pending",
    )
    return JSONResponse(
        {"status": "pending_human", "proposal": proposal_view(attached, "pending")},
        status_code=202,
    )


def _applied_response(proposal):
    return JSONResponse(
        {
            "status": "ok",
            "level": proposal.level,
            "scope_id": proposal.scope_id,
            "provider": proposal.provider,
            "model": proposal.model,
            "modality": proposal.modality,
            "base_url": proposal.base_url,
            "proposal_id": proposal.id,
        }
    )


def _register_ai_key_read_route(app, P, K, ai_config_view) -> None:
    @app.get("/v1/ai-keys")
    async def list_ai_keys(k=K, p=P) -> dict:
        configs = await k.store.list_ai_configs(p.tenant_id)
        org = await k.store.get_org(p.tenant_id)
        from boltrig.identity import AiKeyResolution
        from boltrig.identity.bifrost_user_binding import BifrostUserGateway

        gateway = None
        try:
            gateway = BifrostUserGateway()
        except Exception:
            pass
        rows = []
        for config in configs:
            view = ai_config_view(config)
            ready = False
            if gateway is not None:
                resolution = AiKeyResolution(
                    level=config.level,
                    scope_id=config.scope_id,
                    modality=config.modality,
                    credential_ref=config.credential_ref,
                    provider=config.provider,
                    model=config.model,
                    base_url=config.base_url,
                )
                binding = await gateway.load(k.store, p.tenant_id, resolution)
                ready = binding is not None and await gateway.is_usable(binding)
            view["gateway_ready"] = ready
            rows.append(view)
        return {
            "allow_own_ai_keys": bool(org.allow_own_ai_keys) if org else False,
            "ai_keys": rows,
        }


def _register_ai_key_set_route(app, P, K, audit, admin_roles, workspace_admin_roles) -> None:
    @app.put("/v1/ai-keys")
    async def set_ai_key(body: dict, k=K, p=P) -> JSONResponse:
        parsed, invalid = _parse_ai_key_intake(body, p)
        if invalid is not None:
            return invalid
        level, scope_id, *_ = parsed
        denied = await _authorize_ai_key(k, p, level, scope_id, admin_roles, workspace_admin_roles)
        if denied is not None:
            return denied
        proposal, secret = _new_proposal(p, parsed)
        _, pending = await _dispatch_staged(k, p, proposal, secret)
        secret = ""
        if pending is not None:
            return await _bind_pending(k, p, proposal, pending, audit)
        await audit(k, p, "ai_key.set", proposal_audit(proposal))
        activated = await activate_ai_key_config(
            k, p, proposal.level, proposal.scope_id, proposal.modality
        )
        if activated is not None:
            return activated
        return _applied_response(proposal)


def _register_ai_key_activate_route(
    app, P, K, admin_roles, workspace_admin_roles
) -> None:
    @app.post("/v1/ai-keys/activate")
    async def activate_ai_key(body: dict, k=K, p=P) -> JSONResponse:
        level = str(body.get("level") or "").strip()
        if level not in AI_CONFIG_LEVELS:
            return _invalid("unknown level")
        default_scope = {"org": p.tenant_id, "user": p.subject}.get(level)
        scope_id = str(body.get("scope_id") or default_scope or "").strip()
        modality = str(body.get("modality") or "text").strip().lower()
        if not scope_id or modality not in AI_CONFIG_MODALITIES:
            return _invalid("scope_id and a supported modality are required")
        denied = await _authorize_ai_key(
            k, p, level, scope_id, admin_roles, workspace_admin_roles
        )
        if denied is not None:
            return denied
        activated = await activate_ai_key_config(k, p, level, scope_id, modality)
        if activated is not None:
            return activated
        return JSONResponse(
            {
                "status": "ok",
                "level": level,
                "scope_id": scope_id,
                "modality": modality,
            }
        )


def _register_ai_key_delete_route(app, P, K, audit, admin_roles, workspace_admin_roles) -> None:
    @app.delete("/v1/ai-keys/{level}/{scope_id}")
    async def delete_ai_key(level: str, scope_id: str, request: Request, k=K, p=P) -> JSONResponse:
        if level not in AI_CONFIG_LEVELS:
            return _invalid("unknown level")
        denied = await _authorize_ai_key(k, p, level, scope_id, admin_roles, workspace_admin_roles)
        if denied is not None:
            return denied
        modality = str(request.query_params.get("modality") or "text").strip().lower()
        if modality not in AI_CONFIG_MODALITIES:
            return _invalid("unknown modality")
        if await k.store.get_ai_config(p.tenant_id, level, scope_id, modality) is None:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        _, pending = await dispatch_control_route(
            k,
            p,
            "control.ai_key.delete",
            {"level": level, "scope_id": scope_id, "modality": modality},
            request=request,
        )
        if pending is not None:
            return pending
        await audit(
            k, p, "ai_key.delete",
            {"level": level, "scope_id": scope_id, "modality": modality},
        )
        return JSONResponse(
            {"status": "ok", "level": level, "scope_id": scope_id, "modality": modality}
        )


def register_ai_key_routes(
    app,
    P,
    K,
    audit,
    ai_config_view,
    admin_roles: frozenset[str],
    workspace_admin_roles: frozenset[str],
) -> None:
    _register_ai_key_read_route(app, P, K, ai_config_view)
    _register_ai_key_set_route(app, P, K, audit, admin_roles, workspace_admin_roles)
    _register_ai_key_activate_route(app, P, K, admin_roles, workspace_admin_roles)
    register_ai_key_proposal_routes(
        app,
        P,
        K,
        audit,
        _authorize_ai_key,
        admin_roles,
        workspace_admin_roles,
    )
    _register_ai_key_delete_route(app, P, K, audit, admin_roles, workspace_admin_roles)
