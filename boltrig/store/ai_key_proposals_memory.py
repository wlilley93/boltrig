"""In-memory one-time AI-key secret proposal persistence."""

from __future__ import annotations

from dataclasses import replace

from boltrig.models import AiConfig, AiKeySecretProposal
from boltrig.models.errors import SchemaValidationError

from .ai_key_proposal_contract import (
    AI_KEY_PROPOSAL_PAGE_LIMIT,
    matches_exact,
    validate_proposal,
)
from .sealing import seal_ref


class AiKeyProposalStoreMem:
    def _init_ai_key_proposal_state(self) -> None:
        self._ai_key_proposals: dict[tuple[str, str], AiKeySecretProposal] = {}

    async def create_ai_key_secret_proposal(self, proposal, secret):
        validate_proposal(proposal, secret)
        key = (proposal.tenant_id, proposal.id)
        secret_key = (proposal.tenant_id, proposal.secret_ref)
        if key in self._ai_key_proposals or secret_key in self._creds:
            raise SchemaValidationError(
                "AI-key proposal already exists", errors=["duplicate proposal"]
            )
        # Seal before either metadata structure becomes externally observable.
        self._creds[secret_key] = seal_ref({"secret": secret, "purpose": "ai_key_proposal"})
        self._ai_key_proposals[key] = replace(proposal)

    async def attach_ai_key_proposal_approval(
        self, tenant_id, proposal_id, requested_by, approval_id
    ):
        key = (tenant_id, proposal_id)
        proposal = self._ai_key_proposals.get(key)
        if (
            proposal is None
            or proposal.requested_by != requested_by
            or proposal.status != "pending"
            or proposal.approval_id is not None
        ):
            return None
        updated = replace(proposal, approval_id=approval_id)
        self._ai_key_proposals[key] = updated
        return replace(updated)

    async def get_ai_key_secret_proposal(self, tenant_id, proposal_id):
        proposal = self._ai_key_proposals.get((tenant_id, proposal_id))
        return None if proposal is None else replace(proposal)

    async def list_ai_key_secret_proposals(self, tenant_id, requested_by, requested_on_behalf_of):
        rows = [
            replace(proposal)
            for (row_tenant, _), proposal in self._ai_key_proposals.items()
            if row_tenant == tenant_id
            and proposal.requested_by == requested_by
            and proposal.requested_on_behalf_of == requested_on_behalf_of
        ]
        rows.sort(key=lambda proposal: (proposal.created_at, proposal.id), reverse=True)
        return rows[:AI_KEY_PROPOSAL_PAGE_LIMIT]

    async def invalidate_ai_key_secret_proposal(
        self, tenant_id, proposal_id, requested_by, terminal_status, now
    ):
        if terminal_status not in {"rejected", "expired", "invalidated"}:
            raise ValueError("invalid proposal terminal status")
        key = (tenant_id, proposal_id)
        proposal = self._ai_key_proposals.get(key)
        if proposal is None or proposal.requested_by != requested_by:
            return None
        if proposal.status != "pending":
            return replace(proposal)
        if proposal.secret_ref is not None:
            self._creds.pop((tenant_id, proposal.secret_ref), None)
        updated = replace(proposal, status=terminal_status, secret_ref=None, updated_at=now)
        self._ai_key_proposals[key] = updated
        return replace(updated)

    async def invalidate_ai_key_proposal_for_approval(
        self, tenant_id, approval_id, terminal_status, now
    ):
        for proposal in tuple(self._ai_key_proposals.values()):
            if (
                proposal.tenant_id == tenant_id
                and proposal.approval_id == approval_id
                and proposal.status == "pending"
            ):
                await self.invalidate_ai_key_secret_proposal(
                    tenant_id,
                    proposal.id,
                    proposal.requested_by,
                    terminal_status,
                    now,
                )
                return True
        return False

    async def expire_due_ai_key_secret_proposals(self, tenant_id, now):
        approval_ids: list[str] = []
        for proposal in tuple(self._ai_key_proposals.values()):
            if (
                proposal.tenant_id == tenant_id
                and proposal.status == "pending"
                and proposal.expires_at <= now
            ):
                await self.invalidate_ai_key_secret_proposal(
                    tenant_id,
                    proposal.id,
                    proposal.requested_by,
                    "expired",
                    now,
                )
                if proposal.approval_id:
                    approval_ids.append(proposal.approval_id)
        return approval_ids

    async def consume_ai_key_secret_proposal(
        self,
        tenant_id,
        proposal_id,
        *,
        requested_by,
        requested_on_behalf_of,
        workspace_id,
        level,
        scope_id,
        provider,
        model,
        base_url,
        secret_digest,
        now,
    ):
        key = (tenant_id, proposal_id)
        proposal = self._ai_key_proposals.get(key)
        if proposal is None or not matches_exact(
            proposal,
            requested_by=requested_by,
            requested_on_behalf_of=requested_on_behalf_of,
            workspace_id=workspace_id,
            level=level,
            scope_id=scope_id,
            provider=provider,
            model=model,
            base_url=base_url,
            secret_digest=secret_digest,
        ):
            return None
        if not self._proposal_is_consumable(tenant_id, proposal, now):
            if proposal.expires_at <= now:
                await self.invalidate_ai_key_secret_proposal(
                    tenant_id, proposal_id, requested_by, "expired", now
                )
            return None
        config = _ai_config_from_proposal(proposal, now)
        previous = self._ai_configs.get((tenant_id, level, scope_id))
        self._ai_configs[(tenant_id, level, scope_id)] = config
        self._ai_key_proposals[key] = replace(
            proposal,
            status="consumed",
            secret_ref=None,
            updated_at=now,
            consumed_at=now,
        )
        if previous is not None and previous.credential_ref != config.credential_ref:
            self._creds.pop((tenant_id, previous.credential_ref), None)
        return replace(config)

    def _proposal_is_consumable(self, tenant_id, proposal, now):
        return (
            proposal.status == "pending"
            and proposal.secret_ref is not None
            and proposal.expires_at > now
            and (tenant_id, proposal.secret_ref) in self._creds
        )


def _ai_config_from_proposal(proposal, now):
    return AiConfig(
        tenant_id=proposal.tenant_id,
        level=proposal.level,
        scope_id=proposal.scope_id,
        provider=proposal.provider,
        model=proposal.model,
        credential_ref=proposal.secret_ref,
        base_url=proposal.base_url,
        created_at=now,
        updated_at=now,
    )


__all__ = ["AiKeyProposalStoreMem"]
