"""Governed AI-key proposal inspection and one-time finalization routes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from boltrig.kernel.ai_key_proposal_views import (
    proposal_audit,
    proposal_params,
    proposal_view,
    state_reason,
)
from boltrig.kernel.control_routes import dispatch_control_route
from boltrig.kernel.invoke_finalization import invoke_approval_state
from boltrig.models import AiKeySecretProposal, utcnow


def _owned_by(proposal, principal) -> bool:
    return (
        proposal is not None
        and proposal.requested_by == principal.subject
        and proposal.requested_on_behalf_of == principal.on_behalf_of
    )


async def _load_owned_proposal(kernel, principal, proposal_id):
    proposal = await kernel.store.get_ai_key_secret_proposal(principal.tenant_id, proposal_id)
    return proposal if _owned_by(proposal, principal) else None


async def proposal_state(kernel, principal, proposal: AiKeySecretProposal) -> str:
    if proposal.status != "pending":
        return proposal.status
    if proposal.workspace_id != principal.active_workspace_id:
        return await _invalidate_state(kernel, principal, proposal, "invalidated")
    if proposal.expires_at <= utcnow():
        state = await _invalidate_state(kernel, principal, proposal, "expired")
        if proposal.approval_id:
            await kernel.store.expire_hitl(principal.tenant_id, proposal.approval_id)
        return state
    if not proposal.approval_id:
        return await _invalidate_state(kernel, principal, proposal, "invalidated")
    try:
        state = (await invoke_approval_state(kernel, principal, proposal.approval_id))["status"]
    except Exception:
        return "unavailable"
    if state in {"rejected", "expired"}:
        await _invalidate_state(kernel, principal, proposal, state)
    elif state == "consumed":
        # Approval consumption without proposal consumption is ambiguous. Delete
        # staging and never claim that the key was applied.
        await _invalidate_state(kernel, principal, proposal, "invalidated")
    return state


async def _invalidate_state(kernel, principal, proposal, state):
    await kernel.store.invalidate_ai_key_secret_proposal(
        principal.tenant_id, proposal.id, principal.subject, state, utcnow()
    )
    return state


async def _finalize_approved(
    kernel,
    principal,
    proposal,
    audit,
    authorize,
    admin_roles,
    workspace_admin_roles,
):
    denied = await authorize(
        kernel,
        principal,
        proposal.level,
        proposal.scope_id,
        admin_roles,
        workspace_admin_roles,
    )
    if denied is not None:
        await _invalidate_state(kernel, principal, proposal, "invalidated")
        return denied
    _, pending = await dispatch_control_route(
        kernel,
        principal,
        "control.ai_key.set",
        {**proposal_params(proposal), "approval_id": proposal.approval_id},
        request=None,
    )
    if pending is not None:
        await _invalidate_reapproval(kernel, principal, proposal, pending)
        return JSONResponse(
            {
                "status": "invalidated",
                "reason": (
                    "Something changed while this was being approved. "
                    "Submit the provider again."
                ),
            },
            status_code=409,
        )
    await audit(kernel, principal, "ai_key.set", proposal_audit(proposal))
    activated = await activate_ai_key_config(
        kernel,
        principal,
        proposal.level,
        proposal.scope_id,
        proposal.modality,
    )
    if activated is not None:
        await audit(
            kernel,
            principal,
            "ai_key.gateway.unavailable",
            proposal_audit(proposal),
            status="unavailable",
        )
        return activated
    return JSONResponse(
        {
            "status": "ok",
            **{
                key: value
                for key, value in proposal_audit(proposal).items()
                if key != "proposal_id"
            },
            "proposal_id": proposal.id,
        }
    )


async def activate_ai_key_config(kernel, principal, level, scope_id, modality):
    """Provision the exact approved key/model into Bifrost, keys-only outward."""

    from boltrig.identity import AiKeyResolution, load_ai_key_material
    from boltrig.identity.bifrost_user_binding import (
        BifrostUserBindingUnavailable,
        BifrostUserGateway,
    )

    config = await kernel.store.get_ai_config(
        principal.tenant_id,
        level,
        scope_id,
        modality,
    )
    if config is None:
        return JSONResponse(
            {
                "status": "unavailable",
                "reason": (
                    "The saved provider details could not be found. "
                    "Submit the provider again."
                ),
            },
            status_code=503,
        )
    resolution = AiKeyResolution(
        level=config.level,
        scope_id=config.scope_id,
        modality=config.modality,
        credential_ref=config.credential_ref,
        provider=config.provider,
        model=config.model,
        base_url=config.base_url,
    )
    material = await load_ai_key_material(kernel.store, principal.tenant_id, resolution)
    if material is None:
        return JSONResponse(
            {
                "status": "unavailable",
                "reason": (
                    "The saved key could not be read. Submit the provider again."
                ),
            },
            status_code=503,
        )
    try:
        await BifrostUserGateway().ensure(
            kernel.store, principal.tenant_id, resolution, material
        )
    # ValueError guards a legacy stored model id the current policy refuses:
    # activation of old rows must answer with a sentence, never a bare 500
    # (measured 2026-08-20: an approved ':latest' row crashed this route).
    except (BifrostUserBindingUnavailable, ValueError) as error:
        return JSONResponse(
            {"status": "unavailable", "reason": str(error)},
            status_code=503,
        )
    return None


async def _invalidate_reapproval(kernel, principal, proposal, pending):
    body = json.loads(bytes(pending.body))
    replacement_id = str(body.get("hitl_request_id") or "")
    if replacement_id:
        await kernel.store.expire_hitl(principal.tenant_id, replacement_id)
    await _invalidate_state(kernel, principal, proposal, "invalidated")


@dataclass(frozen=True)
class _RouteDeps:
    app: Any
    principal: Any
    kernel: Any
    audit: Any
    authorize: Any
    admin_roles: Any
    workspace_admin_roles: Any


def _register_proposal_read_routes(deps: _RouteDeps) -> None:
    @deps.app.get("/v1/ai-keys/proposals")
    async def list_ai_key_proposals(k=deps.kernel, p=deps.principal) -> dict:
        proposals = await k.store.list_ai_key_secret_proposals(
            p.tenant_id, p.subject, p.on_behalf_of
        )
        return {
            "proposals": [
                proposal_view(proposal, await proposal_state(k, p, proposal))
                for proposal in proposals
            ]
        }

    @deps.app.get("/v1/ai-keys/proposals/{proposal_id}")
    async def get_ai_key_proposal(proposal_id: str, k=deps.kernel, p=deps.principal):
        proposal = await _load_owned_proposal(k, p, proposal_id)
        if proposal is None:
            return _not_found()
        state = await proposal_state(k, p, proposal)
        return JSONResponse({"status": state, "proposal": proposal_view(proposal, state)})


async def finalize_owned_proposal(
    kernel,
    principal,
    proposal_id: str,
    audit,
    authorize,
    admin_roles,
    workspace_admin_roles,
) -> JSONResponse:
    """Finalize the caller's proposal if approved, else answer with a sentence."""

    proposal = await _load_owned_proposal(kernel, principal, proposal_id)
    if proposal is None:
        return _not_found()
    state = await proposal_state(kernel, principal, proposal)
    if state != "approved":
        return JSONResponse(
            {
                "status": state,
                "reason": state_reason(state),
                "proposal": proposal_view(proposal, state),
            },
            status_code=202 if state == "pending" else 409,
        )
    return await _finalize_approved(
        kernel,
        principal,
        proposal,
        audit,
        authorize,
        admin_roles,
        workspace_admin_roles,
    )


async def approve_owned_proposal(kernel, principal, proposal) -> JSONResponse | None:
    """Answer the caller's own pending approval; None means it went through.

    The requester approving their own submission carries no oversight, so the
    HITL layer's own policy decides whether that answer is acceptable; a
    refusal comes back as a response for the caller rather than an exception.
    """

    from boltrig.kernel.hitl_http import respond_to_hitl

    try:
        await respond_to_hitl(
            kernel,
            principal,
            proposal.approval_id,
            "approve",
            "Approved during provider setup",
        )
    except HTTPException as error:
        return JSONResponse(
            {"status": "denied", "reason": str(error.detail)},
            status_code=error.status_code,
        )
    return None


def _register_finalize_route(deps: _RouteDeps) -> None:
    @deps.app.post("/v1/ai-keys/proposals/{proposal_id}/finalize")
    async def finalize_ai_key_proposal(
        proposal_id: str, k=deps.kernel, p=deps.principal
    ) -> JSONResponse:
        return await finalize_owned_proposal(
            k,
            p,
            proposal_id,
            deps.audit,
            deps.authorize,
            deps.admin_roles,
            deps.workspace_admin_roles,
        )


def _register_approve_route(deps: _RouteDeps) -> None:
    @deps.app.post("/v1/ai-keys/proposals/{proposal_id}/approve")
    async def approve_and_finalize_ai_key_proposal(
        proposal_id: str, k=deps.kernel, p=deps.principal
    ) -> JSONResponse:
        """Explicit requester click; hidden approval id never crosses HTTP."""

        proposal = await _load_owned_proposal(k, p, proposal_id)
        if proposal is None:
            return _not_found()
        state = await proposal_state(k, p, proposal)
        if state == "pending":
            refused = await approve_owned_proposal(k, p, proposal)
            if refused is not None:
                return refused
        return await finalize_owned_proposal(
            k,
            p,
            proposal_id,
            deps.audit,
            deps.authorize,
            deps.admin_roles,
            deps.workspace_admin_roles,
        )


def _register_invalidate_route(deps: _RouteDeps) -> None:
    @deps.app.delete("/v1/ai-keys/proposals/{proposal_id}")
    async def invalidate_ai_key_proposal(
        proposal_id: str, k=deps.kernel, p=deps.principal
    ) -> JSONResponse:
        proposal = await _load_owned_proposal(k, p, proposal_id)
        if proposal is None:
            return _not_found()
        invalidated = await k.store.invalidate_ai_key_secret_proposal(
            p.tenant_id, proposal.id, p.subject, "invalidated", utcnow()
        )
        if proposal.approval_id:
            await k.store.expire_hitl(p.tenant_id, proposal.approval_id)
        await deps.audit(k, p, "ai_key.proposal.invalidate", proposal_audit(proposal))
        result = invalidated or proposal
        state = invalidated.status if invalidated is not None else "invalidated"
        return JSONResponse({"status": state, "proposal": proposal_view(result, state)})


def register_ai_key_proposal_routes(
    app,
    P,
    K,
    audit,
    authorize,
    admin_roles,
    workspace_admin_roles,
) -> None:
    deps = _RouteDeps(
        app, P, K, audit, authorize, admin_roles, workspace_admin_roles
    )
    _register_proposal_read_routes(deps)
    _register_finalize_route(deps)
    _register_approve_route(deps)
    _register_invalidate_route(deps)


def _not_found():
    return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)


__all__ = [
    "activate_ai_key_config",
    "approve_owned_proposal",
    "finalize_owned_proposal",
    "proposal_audit",
    "proposal_params",
    "proposal_view",
    "register_ai_key_proposal_routes",
    "state_reason",
]
