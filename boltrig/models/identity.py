"""Identity records (S6.5): users and IdP-group -> role/scope mappings."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .base import TenantId, UserId, utcnow


@dataclass
class User:
    """A provisioned user. Provisioned just-in-time on first authenticated login
    (US-USR-01) and the authority for the user's *current* role/scope/status, so
    a PAT re-checks against it and a deactivated user's access (and tokens) stop
    working at once (US-USR-03, SEC-34)."""

    id: UserId  # subject from the IdP
    tenant_id: TenantId
    email: str | None = None
    display_name: str | None = None
    groups: list[str] = field(default_factory=list)  # IdP groups, synced
    role: str = "none"  # resolved platform role (fail-closed default)
    scope: dict[str, Any] = field(default_factory=dict)  # departments/nouns/verbs visible
    status: str = "active"  # active | deactivated (deactivation revokes access)
    source: str = "idp"  # idp | invitation (how the role/scope was conferred)
    source_group: str | None = None  # the IdP group that conferred the role (US-USR-04)
    last_seen_at: datetime | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class RoleMapping:
    tenant_id: TenantId
    idp_group: str  # AD/Okta/Google group
    role: str  # platform role
    scope: dict[str, Any] = field(default_factory=dict)  # departments/nouns/verbs visible
