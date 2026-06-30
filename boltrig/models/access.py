"""Round Four access models: personal access tokens, invitations, settings,
sessions (S R4 Ch.4).

These carry ``tenant_id`` and are tenant-isolated. A personal access token's
authority is the intersection of its declared ``scope`` and the owner's *current*
grants, re-checked on every call (SEC-34): it can never exceed the user, is
bounded by a required expiry, is stored only as a hash, and is revocable. An
invitation only pre-stages a role/scope for an SSO-authenticated identity; it
creates no password and grants no access until the invitee authenticates through
the IdP (SEC-35).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .base import TenantId, UserId, utcnow


# --- personal access tokens (SET-40 / PAT-*, SEC-34) -------------------------
@dataclass
class PersonalAccessToken:
    id: str
    tenant_id: TenantId
    user_id: UserId
    name: str
    token_hash: str  # sha256 of the secret; the secret is shown once at creation
    scope: list[str]  # allow-patterns, a subset of the user's grants (never escalates)
    created_at: datetime = field(default_factory=utcnow)
    expires_at: datetime | None = None  # required + bounded in practice (PAT-03)
    last_used_at: datetime | None = None
    revoked: bool = False


# --- admin invitations (US-USR-02, SEC-35) -----------------------------------
@dataclass
class UserInvitation:
    id: str
    tenant_id: TenantId
    email: str
    intended_role: str
    intended_scope: dict[str, Any]
    invited_by: str
    created_at: datetime = field(default_factory=utcnow)
    expires_at: datetime | None = None
    status: str = "pending"  # pending | accepted | revoked | expired


# --- per-user settings/preferences (SET-*) -----------------------------------
@dataclass
class UserSetting:
    tenant_id: TenantId
    user_id: UserId
    key: str  # 'theme' | 'locale' | 'timezone' | 'a11y.reduced_motion' | ...
    value: Any
    updated_at: datetime = field(default_factory=utcnow)


# --- sessions (SET-70) -------------------------------------------------------
@dataclass
class UserSession:
    id: str
    tenant_id: TenantId
    user_id: UserId
    client: str | None = None  # 'web' | 'claude-code' | 'teams' | ...
    created_at: datetime = field(default_factory=utcnow)
    last_seen_at: datetime | None = None
    revoked: bool = False
