"""Identity records (S6.5): users and IdP-group -> role/scope mappings."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import TenantId, UserId


@dataclass
class User:
    id: UserId  # subject from the IdP
    tenant_id: TenantId
    email: str | None = None
    display_name: str | None = None
    groups: list[str] = field(default_factory=list)  # IdP groups, synced


@dataclass
class RoleMapping:
    tenant_id: TenantId
    idp_group: str  # AD/Okta/Google group
    role: str  # platform role
    scope: dict[str, Any] = field(default_factory=dict)  # departments/nouns/verbs visible
