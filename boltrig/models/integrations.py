"""Canonical tenant-scoped integration catalogue and connection records.

Catalogue metadata is reviewed data, not a hard-coded provider switch.  A
connection names an adapter and an optional credential *reference*; credential
material is deliberately absent from both records and every public projection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .base import TenantId, utcnow
from .integration_auth import IntegrationSecretContract

INTEGRATION_CATEGORIES = (
    "communications",
    "work",
    "storage_design",
    "crm_sales",
    "finance",
    "analytics_operations",
    "browser",
)
INTEGRATION_TRANSPORTS = ("rest", "mcp", "channel_gateway", "browser")
INTEGRATION_AUTH_KINDS = ("oauth2", "manual_secret", "channel_pairing")
INTEGRATION_CERTIFICATIONS = (
    "uncertified",
    "certifying",
    "certified",
    "suspended",
)
INTEGRATION_HEALTH = ("pending", "ok", "degraded", "down", "revoked")


@dataclass
class IntegrationCatalogueRecord:
    id: str
    tenant_id: TenantId
    label: str
    category: str
    transport: str
    description: str
    certification: str = "uncertified"
    auth: list[str] = field(default_factory=list)
    adapter_id: str | None = None
    secret_contract: IntegrationSecretContract | None = None
    setup_copy: str | None = None
    access_copy: str | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        if self.category not in INTEGRATION_CATEGORIES:
            raise ValueError("unsupported integration category")
        if self.transport not in INTEGRATION_TRANSPORTS:
            raise ValueError("unsupported integration transport")
        if self.certification not in INTEGRATION_CERTIFICATIONS:
            raise ValueError("unsupported integration certification")
        if any(kind not in INTEGRATION_AUTH_KINDS for kind in self.auth):
            raise ValueError("unsupported integration auth kind")
        if self.secret_contract is not None and "manual_secret" not in self.auth:
            raise ValueError("manual secret contract requires manual_secret auth")


@dataclass
class IntegrationConnection:
    id: str
    tenant_id: TenantId
    integration_id: str
    adapter_id: str
    label: str
    health: str = "pending"
    credential_ref: str | None = None
    credential_owned: bool = False
    accounts: list[dict[str, object]] = field(default_factory=list)
    last_checked_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        if self.health not in INTEGRATION_HEALTH:
            raise ValueError("unsupported integration health")
