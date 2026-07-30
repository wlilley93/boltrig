"""Governed AI-key proposal inspection and one-time finalization routes."""

from __future__ import annotations

import json

from fastapi.responses import JSONResponse

from boltrig.kernel.control_routes import dispatch_control_route
from boltrig.kernel.invoke_finalization import invoke_approval_state
from boltrig.models import AiKeySecretProposal, utcnow


def proposal_params(proposal: AiKeySecretProposal) -> dict:
    return {
        "level": proposal.level,
        "scope_id": proposal.scope_id,
        "provider": proposal.provider,
        "model": proposal.model,
        **({"base_url": proposal.base_url} if proposal.base_url is not None else {}),
        "proposal_id": proposal.id,
        "secret_digest": proposal.secret_digest,
    }


def proposal_view(proposal: AiKeySecretProposal, status: str) -> dict:
    return {
        "id": proposal.id,
        "level": proposal.level,
        "scope_id": proposal.scope_id,
        "provider": proposal.provider,
        "model": proposal.model,
        "base_url": proposal.base_url,
        "status": status,
        "created_at": proposal.created_at.isoformat(),
        "expires_at": proposal.expires_at.isoformat(),
    }


def proposal_audit(proposal: AiKeySecretProposal) -> dict:
    return {
        "proposal_id": proposal.id,
        "level": proposal.level,
        "scope_id": proposal.scope_id,
        "provider": proposal.provider,
        "model": proposal.model,
        "base_url": proposal.base_url,
    }


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
                "reason": "caller or governed resource changed after approval",
            },
            status_code=409,
        )
    await audit(kernel, principal, "ai_key.set", proposal_audit(proposal))
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


async def _invalidate_reapproval(kernel, principal, proposal, pending):
    body = json.loads(bytes(pending.body))
    replacement_id = str(body.get("hitl_request_id") or "")
    if replacement_id:
        await kernel.store.expire_hitl(principal.tenant_id, replacement_id)
    await _invalidate_state(kernel, principal, proposal, "invalidated")


def register_ai_key_proposal_routes(
    app,
    P,
    K,
    audit,
    authorize,
    admin_roles,
    workspace_admin_roles,
) -> None:
    @app.get("/v1/ai-keys/proposals")
    async def list_ai_key_proposals(k=K, p=P) -> dict:
        proposals = await k.store.list_ai_key_secret_proposals(
            p.tenant_id, p.subject, p.on_behalf_of
        )
        return {
            "proposals": [
                proposal_view(proposal, await proposal_state(k, p, proposal))
                for proposal in proposals
            ]
        }

    @app.get("/v1/ai-keys/proposals/{proposal_id}")
    async def get_ai_key_proposal(proposal_id: str, k=K, p=P) -> JSONResponse:
        proposal = await _load_owned_proposal(k, p, proposal_id)
        if proposal is None:
            return _not_found()
        state = await proposal_state(k, p, proposal)
        return JSONResponse({"status": state, "proposal": proposal_view(proposal, state)})

    @app.post("/v1/ai-keys/proposals/{proposal_id}/finalize")
    async def finalize_ai_key_proposal(proposal_id: str, k=K, p=P) -> JSONResponse:
        proposal = await _load_owned_proposal(k, p, proposal_id)
        if proposal is None:
            return _not_found()
        state = await proposal_state(k, p, proposal)
        if state != "approved":
            return JSONResponse(
                {"status": state, "proposal": proposal_view(proposal, state)},
                status_code=202 if state == "pending" else 409,
            )
        return await _finalize_approved(
            k,
            p,
            proposal,
            audit,
            authorize,
            admin_roles,
            workspace_admin_roles,
        )

    @app.delete("/v1/ai-keys/proposals/{proposal_id}")
    async def invalidate_ai_key_proposal(proposal_id: str, k=K, p=P) -> JSONResponse:
        proposal = await _load_owned_proposal(k, p, proposal_id)
        if proposal is None:
            return _not_found()
        invalidated = await k.store.invalidate_ai_key_secret_proposal(
            p.tenant_id, proposal.id, p.subject, "invalidated", utcnow()
        )
        if proposal.approval_id:
            await k.store.expire_hitl(p.tenant_id, proposal.approval_id)
        await audit(k, p, "ai_key.proposal.invalidate", proposal_audit(proposal))
        result = invalidated or proposal
        state = invalidated.status if invalidated is not None else "invalidated"
        return JSONResponse({"status": state, "proposal": proposal_view(result, state)})


def _not_found():
    return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)


__all__ = [
    "proposal_audit",
    "proposal_params",
    "proposal_view",
    "register_ai_key_proposal_routes",
]
