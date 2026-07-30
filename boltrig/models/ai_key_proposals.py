"""Opaque, secret-free records for staged AI-key approval."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .base import TenantId, UserId, utcnow


AI_KEY_PROPOSAL_STATUSES: frozenset[str] = frozenset(
    {"pending", "consumed", "rejected", "expired", "invalidated"}
)


@dataclass
class AiKeySecretProposal:
    """Metadata for one sealed, short-lived AI-key proposal.

    ``secret_ref`` names an envelope-sealed credential row. The secret itself is
    never a field on this record, so normal proposal reads and representations
    cannot disclose it.
    """

    id: str
    tenant_id: TenantId
    requested_by: UserId
    requested_on_behalf_of: UserId | None
    workspace_id: str | None
    level: str
    scope_id: str
    provider: str
    model: str
    base_url: str | None
    secret_ref: str | None
    secret_digest: str
    status: str = "pending"
    approval_id: str | None = None
    created_at: datetime = field(default_factory=utcnow)
    expires_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    consumed_at: datetime | None = None


__all__ = ["AI_KEY_PROPOSAL_STATUSES", "AiKeySecretProposal"]
