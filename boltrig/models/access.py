"""Round Four access models: personal access tokens, invitations, settings,
sessions (S R4 Ch.4).

These carry ``tenant_id`` and are tenant-isolated. A personal access token's
authority is the intersection of its declared ``scope`` and the owner's *current*
grants, re-checked on every call (SEC-34): it can never exceed the user, is
bounded by a required expiry, is stored only as a hash, and is revocable. An
invitation only pre-stages a role/scope for an SSO-authenticated identity; it
creates no password and grants no access until the invitee authenticates through
the IdP (SEC-35).

First-party invite-only login ([2026] VJS-COUNTY 7) reuses these same records: an
``UserInvitation`` optionally carries a single-use HASHED, EXPIRING invite token
(``token_hash``, the secret shown once, never stored in the clear) that the
accept-invite flow consumes to set a password; a ``UserSession`` becomes a
Boltrig-issued browser session carrying its own hashed opaque secret
(``token_hash``), a bounded ``expires_at``, and a session-bound CSRF token. No
password ever lives on these records - the password hash is a credential kept
apart from the identity row (see the store's password-credential seam).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .base import TenantId, UserId, WorkspaceId, utcnow


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
    # First-party invite-only login ([2026] VJS-COUNTY 7, D1): the sha256 of a
    # single-use invite-token secret. The secret is shown ONCE at invite creation
    # and never stored; accept-invite hashes the presented token and matches it
    # here. None for a legacy SSO-only invitation that carries no token.
    token_hash: str | None = None


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
    # First-party session login ([2026] VJS-COUNTY 7, D2/D6). The cookie carries a
    # high-entropy opaque secret; only its sha256 is persisted here (token_hash),
    # mirroring the SEC-34 PAT pattern. expires_at bounds the session lifetime
    # (fail-closed once past); csrf_token is the session-bound double-submit token
    # a mutating cookie request must echo in the X-Boltrig-CSRF header. All three
    # are None for a legacy directory-listing session row that carries no secret.
    token_hash: str | None = None
    expires_at: datetime | None = None
    csrf_token: str | None = None
    # The session's ACTIVE WORKSPACE ([2026] VJS-COUNTY 8, D4). Nullable: it is the
    # workspace the user last switched to (POST /v1/me/active-context) or the default
    # resolved from membership at login, and None when the user has no workspace yet.
    # It is a HINT persisted on the session, NEVER trusted on its own: the resolver
    # RE-AUTHORIZES membership against workspace_members every request and drops to
    # None if the user is no longer a member (fail-closed), so a stale row can never
    # grant workspace access.
    active_workspace_id: WorkspaceId | None = None
