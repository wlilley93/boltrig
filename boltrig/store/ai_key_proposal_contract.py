"""Contract and shared validation for one-time AI-key secret proposals."""

from __future__ import annotations

import hmac
from datetime import datetime, timedelta
from typing import Any, Protocol

from boltrig.models import (
    AI_CONFIG_LEVELS,
    AI_CONFIG_MODALITIES,
    AiConfig,
    AiKeySecretProposal,
)
from boltrig.models.errors import SchemaValidationError

AI_KEY_PROPOSAL_MAX_TTL = timedelta(minutes=15)
AI_KEY_PROPOSAL_PAGE_LIMIT = 20


def validate_proposal(proposal: AiKeySecretProposal, secret: str) -> None:
    if (
        proposal.level not in AI_CONFIG_LEVELS
        or proposal.modality not in AI_CONFIG_MODALITIES
        or proposal.status != "pending"
        or not proposal.id.startswith("akp_")
        or proposal.secret_ref is None
        or not proposal.secret_ref.startswith("staged_ai_key:")
        or len(proposal.secret_digest) != 64
        or any(ch not in "0123456789abcdef" for ch in proposal.secret_digest)
        or not proposal.requested_by
        or not proposal.scope_id
        or not proposal.provider
        or not proposal.model
        or not secret
        or proposal.expires_at <= proposal.created_at
        or proposal.expires_at > proposal.created_at + AI_KEY_PROPOSAL_MAX_TTL
    ):
        raise SchemaValidationError(
            "invalid AI-key secret proposal",
            errors=["proposal must be bounded, secret-free metadata with a sealed secret"],
        )


def proposal_from_row(row: Any) -> AiKeySecretProposal | None:
    if row is None:
        return None
    return AiKeySecretProposal(
        id=row["id"],
        tenant_id=row["tenant_id"],
        requested_by=row["requested_by"],
        requested_on_behalf_of=row["requested_on_behalf_of"],
        workspace_id=row["workspace_id"],
        level=row["level"],
        scope_id=row["scope_id"],
        provider=row["provider"],
        model=row["model"],
        base_url=row["base_url"],
        modality=row["modality"] if "modality" in row else "text",
        secret_ref=row["secret_ref"],
        secret_digest=row["secret_digest"],
        status=row["status"],
        approval_id=row["approval_id"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        updated_at=row["updated_at"],
        consumed_at=row["consumed_at"],
    )


def matches_exact(
    proposal: AiKeySecretProposal,
    *,
    requested_by: str,
    requested_on_behalf_of: str | None,
    workspace_id: str | None,
    level: str,
    scope_id: str,
    provider: str,
    model: str,
    base_url: str | None,
    modality: str,
    secret_digest: str,
) -> bool:
    return (
        proposal.requested_by == requested_by
        and proposal.requested_on_behalf_of == requested_on_behalf_of
        and proposal.workspace_id == workspace_id
        and proposal.level == level
        and proposal.scope_id == scope_id
        and proposal.provider == provider
        and proposal.model == model
        and proposal.base_url == base_url
        and proposal.modality == modality
        and hmac.compare_digest(proposal.secret_digest, secret_digest)
    )


class AiKeyProposalStoreContract(Protocol):
    async def create_ai_key_secret_proposal(
        self, proposal: AiKeySecretProposal, secret: str
    ) -> None: ...

    async def attach_ai_key_proposal_approval(
        self,
        tenant_id: str,
        proposal_id: str,
        requested_by: str,
        approval_id: str,
    ) -> AiKeySecretProposal | None: ...

    async def get_ai_key_secret_proposal(
        self, tenant_id: str, proposal_id: str
    ) -> AiKeySecretProposal | None: ...

    async def list_ai_key_secret_proposals(
        self,
        tenant_id: str,
        requested_by: str,
        requested_on_behalf_of: str | None,
    ) -> list[AiKeySecretProposal]: ...

    async def invalidate_ai_key_secret_proposal(
        self,
        tenant_id: str,
        proposal_id: str,
        requested_by: str,
        terminal_status: str,
        now: datetime,
    ) -> AiKeySecretProposal | None: ...

    async def invalidate_ai_key_proposal_for_approval(
        self,
        tenant_id: str,
        approval_id: str,
        terminal_status: str,
        now: datetime,
    ) -> bool: ...

    async def expire_due_ai_key_secret_proposals(
        self, tenant_id: str, now: datetime
    ) -> list[str]: ...

    async def consume_ai_key_secret_proposal(
        self,
        tenant_id: str,
        proposal_id: str,
        *,
        requested_by: str,
        requested_on_behalf_of: str | None,
        workspace_id: str | None,
        level: str,
        scope_id: str,
        provider: str,
        model: str,
        base_url: str | None,
        secret_digest: str,
        now: datetime,
        modality: str = "text",
    ) -> AiConfig | None: ...


__all__ = [
    "AI_KEY_PROPOSAL_MAX_TTL",
    "AI_KEY_PROPOSAL_PAGE_LIMIT",
    "AiKeyProposalStoreContract",
    "matches_exact",
    "proposal_from_row",
    "validate_proposal",
]
