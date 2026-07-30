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
    # Org/workspace-scoped invites + provisioning ([2026] VJS-COUNTY 8, D6). All
    # three are nullable and additive; a legacy invite leaves them None and behaves
    # exactly as before. ``workspace_id`` targets an EXISTING workspace: on accept
    # the invitee is seated into it as a workspace member with the invited role
    # (bounded by the SEC-102 privilege ceiling). ``provision_workspace_name`` asks
    # accept to CREATE that workspace and seat the invitee as its owner.
    # ``provision_org_name`` asks accept to provision a brand-new organisation owned
    # by the invitee - it is SUPERADMIN-ONLY at invite creation (a lesser admin may
    # never set it). The inviter must be able to manage a targeted ``workspace_id``.
    workspace_id: WorkspaceId | None = None
    provision_workspace_name: str | None = None
    provision_org_name: str | None = None


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
    # The session's ACTIVE ORG ([2026] VJS-COUNTY 11, D2/D3). One email can belong to
    # several orgs (tenants); this is the ONE the session is currently bound to - the
    # single active tenant every request is scoped to. Like active_workspace_id it is a
    # HINT persisted on the session, NEVER trusted on its own: the resolver
    # RE-AUTHORIZES it against org_members every request and rebinds the RLS tenant to
    # it, and an org SWITCH (POST /v1/me/active-org) is the only way it changes. None on
    # a legacy / single-org session, where the resolver falls back to the session's own
    # tenant (backward-compatible).
    active_org_id: TenantId | None = None


# --- TOTP two-factor ([2026] VJS-COUNTY 10) ----------------------------------
@dataclass
class UserTotp:
    """A user's TOTP second-factor enrolment state, kept in its OWN table apart
    from the identity row (like the password credential).

    ``secret_ref`` is the id of a SEALED credential in ``credential_refs`` holding
    the base32 TOTP shared secret (D1) - NEVER a plaintext secret column here.
    ``enrolled`` is False for a begun-but-unconfirmed enrolment (the secret exists
    but no session-issuing factor challenge accepts it yet) and True only after a
    verify-enroll code confirms the authenticator (D3). One row per (tenant, user).
    """

    tenant_id: TenantId
    user_id: UserId
    secret_ref: str  # id into credential_refs (the SEALED base32 secret); never the secret
    enrolled: bool = False
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass
class TwoFactorChallenge:
    """A pending login second-factor challenge ([2026] VJS-COUNTY 10, D3).

    Minted after the password verifies when 2FA is due; it carries NO access on its
    own (no session is issued) - it only lets a follow-up TOTP/recovery-code verify
    issue the session. Only the sha256 of the challenge token is persisted
    (``token_hash``, mirroring the session/PAT pattern); the token itself lives only
    in the login response. Short-lived (``expires_at``) and single-use (consumed on
    a successful factor)."""

    tenant_id: TenantId
    token_hash: str  # sha256 of the challenge token; never the token
    user_id: UserId
    expires_at: datetime
    created_at: datetime = field(default_factory=utcnow)


# --- password recovery (SEC-AUTH-RECOVERY-01) -------------------------------
@dataclass
class PasswordResetToken:
    """The durable, single-use password-reset claim.

    Only ``token_hash`` is persisted. The plaintext reset secret exists solely in
    the delivery notice and is never represented by this store-facing model.
    """

    tenant_id: TenantId
    user_id: UserId
    token_hash: str
    expires_at: datetime
    created_at: datetime = field(default_factory=utcnow)
    consumed_at: datetime | None = None


@dataclass(frozen=True)
class PasswordResetResult:
    """Bounded result of an atomic reset, safe for audit and API control flow."""

    user_id: UserId
    revoked_sessions: int
