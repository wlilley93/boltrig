"""Pure projections of an AI-key proposal: params, views, audit rows, copy."""

from __future__ import annotations

from boltrig.models import AiKeySecretProposal


def proposal_params(proposal: AiKeySecretProposal) -> dict:
    return {
        "level": proposal.level,
        "scope_id": proposal.scope_id,
        "provider": proposal.provider,
        "model": proposal.model,
        "modality": proposal.modality,
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
        "modality": proposal.modality,
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
        "modality": proposal.modality,
        "base_url": proposal.base_url,
    }


#: One plain sentence per non-approved proposal state. These travel to the
#: person who pressed the button, so they say what to DO, not what subsystem
#: said no; a state missing here falls back to the resubmit sentence.
_STATE_REASONS = {
    "pending": "This connection is waiting for an administrator's approval.",
    "expired": "This request expired before it finished. Submit the provider again.",
    "unavailable": "The approval could not be checked just now. Try again.",
}
_STATE_REASON_FALLBACK = "This request can no longer be used. Submit the provider again."


def state_reason(state: str) -> str:
    return _STATE_REASONS.get(state, _STATE_REASON_FALLBACK)


__all__ = [
    "proposal_audit",
    "proposal_params",
    "proposal_view",
    "state_reason",
]
