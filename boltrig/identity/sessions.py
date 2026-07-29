"""First-party browser sessions + the session principal resolver ([2026] VJS-COUNTY 7).

After a first-party email/password login the kernel issues a Boltrig session: a
high-entropy opaque secret set as an httpOnly + Secure + SameSite cookie, whose
sha256 alone is persisted in the existing ``user_sessions`` store (mirroring the
SEC-34 PAT pattern). The session is bounded (``expires_at``), rotating (a refresh
mints a new secret) and revocable (logout / the sessions panel flip ``revoked``).

``build_session_resolver`` is the ``PrincipalResolver`` selected by bootstrap in
place of ``build_cf_access_resolver``: it verifies the cookie against the store,
resolves the current user (deactivation kills the session at once, fail-closed),
and enforces CSRF on mutating cookie requests. Identity comes only from the
verified session, never from the request body (SEC-02).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import timedelta

from fastapi import HTTPException, Request

from boltrig.kernel.app import Principal, PrincipalResolver
from boltrig.models import UserSession, utcnow

from .provisioning import effective_grants_for_request

# Cookie + header names (the login-UI seat builds against these).
SESSION_COOKIE = "boltrig_session"
CSRF_COOKIE = "boltrig_csrf"  # readable-by-JS mirror of the session CSRF token
CSRF_HEADER = "x-boltrig-csrf"  # must be echoed on every mutating cookie request

# Bounded session lifetime (D6). Kept modest; a refresh rotates + extends it.
SESSION_TTL_HOURS = 12
# Absolute, creation-anchored cap (D6, "bounded lifetime"): a session may slide
# via refresh only up to this age from created_at, then it must re-authenticate.
# Without this, refresh-before-expiry could keep a session (or a captured then
# refreshed one) alive indefinitely.
SESSION_ABSOLUTE_MAX_HOURS = 24 * 7
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Two-factor enrollment-only clamp ([2026] VJS-COUNTY 10, D4). When the org requires
# 2FA and the caller has NOT activated a factor, the resolver clamps their session to
# the enrollment surface ONLY: every authenticated route is refused EXCEPT these. This
# also covers the edge case where an admin flips require_two_factor ON while the user
# already holds a full session - they are clamped on their very next request.
_ENROLLMENT_ONLY_ALLOWED = frozenset({
    "/v1/auth/2fa/enroll",
    "/v1/auth/2fa/verify-enroll",
    "/v1/auth/logout",
})

# Forced-rotation clamp ([2026] VJS-COUNTY 8, D7). Same shape and the same
# reasoning as the enrollment clamp above: an account still carrying its
# PROVISIONING credential reaches the change-password surface and nothing else.
# Checked every request, not just at login, so a flag set while a session is live
# takes effect on the very next call.
_PASSWORD_CHANGE_ONLY_ALLOWED = frozenset({
    "/v1/auth/change-password",
    "/v1/auth/logout",
})


def _prefix() -> str:
    return "boltrig_sess_"


def generate_session_secret() -> str:
    """A fresh high-entropy session secret (the cookie value; never stored raw)."""
    return _prefix() + secrets.token_urlsafe(32)


def hash_session_secret(secret: str) -> str:
    """The at-rest representation of a session: its sha256, never the secret."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _new_csrf() -> str:
    return secrets.token_urlsafe(24)


def new_session(
    tenant_id: str, user_id: str, *, client: str | None = "web"
) -> tuple[UserSession, str, str]:
    """Build a fresh :class:`UserSession` plus its ``(secret, csrf_token)``.

    The caller persists the returned session via ``store.add_session`` and sets the
    secret + csrf token as cookies. Only the hash is stored; the secret leaves in
    the Set-Cookie header and is never persisted or logged (D2/D6).
    """
    now = utcnow()
    secret = generate_session_secret()
    csrf = _new_csrf()
    session = UserSession(
        id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        user_id=user_id,
        client=client,
        created_at=now,
        last_seen_at=now,
        revoked=False,
        token_hash=hash_session_secret(secret),
        expires_at=now + timedelta(hours=SESSION_TTL_HOURS),
        csrf_token=csrf,
    )
    return session, secret, csrf


def rotate_session(session: UserSession) -> tuple[UserSession, str, str]:
    """Rotate a live session's secret + CSRF token in place (D6, rotating sessions).

    Returns the same session object (id preserved so the sessions panel entry is
    stable) with a new hash, a fresh CSRF token, and an extended bounded expiry,
    plus the new ``(secret, csrf_token)`` for the caller to re-cookie. The OLD
    secret's hash no longer matches, so a captured old cookie stops working.
    """
    now = utcnow()
    if session.created_at is not None and (
        now >= session.created_at + timedelta(hours=SESSION_ABSOLUTE_MAX_HOURS)
    ):
        # Past the absolute cap: refuse to extend, forcing re-authentication.
        raise ValueError("session past absolute lifetime cap")
    secret = generate_session_secret()
    csrf = _new_csrf()
    session.token_hash = hash_session_secret(secret)
    session.csrf_token = csrf
    session.expires_at = now + timedelta(hours=SESSION_TTL_HOURS)
    session.last_seen_at = now
    return session, secret, csrf


def pick_default_workspace(workspaces) -> str | None:
    """Pick the DETERMINISTIC default active workspace from a user's memberships.

    Used on login to seed the session's active workspace ([2026] VJS-COUNTY 8, D4).
    Ordered by (created_at, id) so the choice is stable regardless of store
    iteration order (the in-memory store preserves insertion order; Postgres does
    not order without an ORDER BY). Returns the workspace id, or None when the user
    is a member of no workspace yet.
    """
    if not workspaces:
        return None
    ordered = sorted(
        workspaces,
        key=lambda w: (w.created_at.isoformat() if w.created_at else "", w.id),
    )
    return ordered[0].id


def pick_default_org(orgs) -> str | None:
    """Pick the DETERMINISTIC default active org from an email's memberships.

    Used on login to seed the session's active org ([2026] VJS-COUNTY 11, D2). The
    store returns the org tenant_ids already sorted, so the smallest id is the stable
    default regardless of iteration order. Returns None when the email is a member of
    no org yet (a legacy / single-org identity - the resolver then falls back to the
    session's own tenant, backward-compatible)."""
    if not orgs:
        return None
    return sorted(orgs)[0]


async def resolve_active_org(
    store, realm_tenant_id: str, session, email: str
) -> str | None:
    """Resolve + RE-AUTHORIZE the session's ACTIVE org against CURRENT membership
    ([2026] VJS-COUNTY 11, D2/D3). Returns the ONE tenant the request must be bound to.

    The rules, fail-closed and never trusting the client:

      - A LEGACY / single-org identity (no rows in the global email -> orgs index)
        resolves to the session's OWN tenant (``realm_tenant_id``), exactly as before
        this change - so an existing single-tenant console is behaviourally unchanged.
      - Otherwise the email belongs to the membership model. The session's persisted
        ``active_org_id`` is only a HINT: it is honoured ONLY if the email is STILL a
        member of it (re-checked against the RLS-fenced ``org_members`` row for that
        org, binding the tenant before the read). If the hint is absent or its
        membership was revoked, a DETERMINISTIC in-membership org is chosen instead
        (again re-authorized). If NO membership survives, this returns None
        (fail-closed) and the caller drops the session.

    The global index only ENUMERATES candidate orgs; ``org_members`` is the authority
    for every accept. This is what guarantees a request is bound to exactly ONE org
    the caller is provably a member of - a client-supplied active org is never trusted.
    """
    from boltrig.store.postgres import set_current_tenant

    orgs = await store.list_orgs_for_email(email)
    if not orgs:
        # No membership pointers. Distinguish a genuinely LEGACY session (single-org /
        # pre-COUNTY-11: login never seeded an active org, so active_org_id is None)
        # from a MEMBERSHIP-MODEL session whose every org was revoked (active_org_id was
        # seeded, so it is not None). The former falls back to the session's own tenant
        # (backward-compatible); the latter must FAIL CLOSED - it must never silently
        # inherit realm access after losing every membership.
        return realm_tenant_id if session.active_org_id is None else None

    async def _is_member(tid: str) -> bool:
        # Bind the candidate tenant BEFORE the RLS-scoped org_members read (SEC-65), so
        # the re-auth is correct under DB-enforced RLS, then confirm the membership row.
        set_current_tenant(tid)
        return await store.get_org_member(tid, email) is not None

    candidate = session.active_org_id
    if candidate and candidate in orgs and await _is_member(candidate):
        return candidate
    for tid in sorted(orgs):
        if await _is_member(tid):
            return tid
    return None


async def resolve_active_workspace(
    store, tenant_id: str, user_id: str, active_workspace_id: str | None
) -> str | None:
    """Re-authorize a session's active workspace against CURRENT membership (D4).

    The active workspace persisted on a session is only a hint: this re-checks, on
    EVERY request, that the user is still a member of it (via
    ``list_workspaces_for_user``, tenant-scoped). If the session carries no active
    workspace, or the workspace no longer exists, or the user's membership has been
    revoked, this returns ``None`` (fail-closed) - never the stale value - so a
    revoked-membership session drops to no active workspace and can never keep
    workspace access it has lost.
    """
    if not active_workspace_id:
        return None
    workspaces = await store.list_workspaces_for_user(tenant_id, user_id)
    if any(w.id == active_workspace_id for w in workspaces):
        return active_workspace_id
    return None


async def resolve_session(store, tenant_id: str, secret: str) -> UserSession | None:
    """Resolve a session cookie secret to a live :class:`UserSession`, else None.

    Fail-closed (D3): an unknown, revoked, or expired session returns ``None``. On
    success the session's ``last_seen_at`` is touched. Tenant-scoped: the lookup is
    bound to the console tenant (the caller binds it first for RLS), so it never
    reaches across tenants.
    """
    if not secret:
        return None
    session = await store.get_session_by_token_hash(tenant_id, hash_session_secret(secret))
    if session is None or session.revoked:
        return None
    if session.expires_at is not None and session.expires_at <= utcnow():
        return None
    session.last_seen_at = utcnow()
    await store.update_session(session)
    return session


def build_session_resolver(tenant_id: str) -> PrincipalResolver:
    """Build the first-party session ``PrincipalResolver`` (D3).

    Selected by bootstrap for the single-tenant console. It reads the session
    cookie, verifies it against the store, resolves the CURRENT user (so an
    admin-deactivated user is denied at once, fail-closed), enforces CSRF on
    mutating cookie requests (D6), and stashes the live session on
    ``request.state`` so the logout / refresh routes can act on it. Identity is
    taken only from the verified session (SEC-02).
    """

    async def resolver(request: Request) -> Principal:
        from boltrig.store.postgres import set_current_tenant

        secret = request.cookies.get(SESSION_COOKIE, "")
        if not secret:
            raise HTTPException(status_code=401, detail="no session")
        store = request.app.state.kernel.store
        # Bind the tenant before any RLS-scoped read (no-op off-RLS / in-memory).
        set_current_tenant(tenant_id)
        session = await resolve_session(store, tenant_id, secret)
        if session is None:
            raise HTTPException(status_code=401, detail="invalid or expired session")

        # Active ORG ([2026] VJS-COUNTY 11, D2/D3): resolve the ONE tenant this request
        # is bound to. The session lives at the identity realm (``tenant_id``); the
        # email may belong to several orgs, so re-authorize the session's active org
        # against CURRENT membership and REBIND the RLS tenant to it for the rest of the
        # request. Never trust a client-supplied active org - the switch route is the
        # only place it changes, and it is membership-checked. A legacy / single-org
        # identity resolves to the realm (backward-compatible). A session whose every
        # membership was revoked drops fail-closed.
        active_org_id = await resolve_active_org(
            store, tenant_id, session, session.user_id
        )
        if active_org_id is None:
            raise HTTPException(status_code=401, detail="invalid or expired session")
        # Bind the active org BEFORE the per-org identity read (SEC-65): the user's
        # role/scope/status is the PER-ORG User row for the active tenant (D1).
        set_current_tenant(active_org_id)
        user = await store.get_user(active_org_id, session.user_id)
        if user is None or user.status != "active":
            # Deactivated / de-provisioned in the active org -> the session is dead for
            # it (fail-closed, D3). One active tenant, provably a member + active.
            raise HTTPException(status_code=401, detail="invalid or expired session")

        # CSRF (D6): a browser attaches the cookie automatically, so a mutating
        # request must ALSO carry the session-bound CSRF token in a custom header
        # a cross-site form cannot set. Safe methods are exempt. Constant-time
        # compare. Bearer/PAT auth never reaches here, so it is not CSRF-gated.
        if request.method in _MUTATING_METHODS:
            presented = request.headers.get(CSRF_HEADER, "")
            if not session.csrf_token or not hmac.compare_digest(
                presented, session.csrf_token
            ):
                raise HTTPException(status_code=403, detail="csrf token missing or invalid")

        # Forced-rotation clamp ([2026] VJS-COUNTY 8, D7). An account whose credential
        # is still the one typed at `boltrig initiate` may reach the change-password
        # surface and logout, nothing else. This runs BEFORE the 2FA clamp and needs
        # no store read of its own - the flag is already on the user row loaded above -
        # so it costs nothing on the overwhelmingly common path where it is False.
        if user.must_change_password and (
            request.url.path not in _PASSWORD_CHANGE_ONLY_ALLOWED
        ):
            raise HTTPException(status_code=403, detail="password_change_required")

        # Two-factor enrollment-only clamp ([2026] VJS-COUNTY 10, D4). If the org
        # requires 2FA and this user has NOT activated a factor, the ONLY surfaces they
        # may reach are enrollment (+ logout); every other authenticated route is
        # refused with a distinct 403 the UI routes to the enrollment screen. This is
        # fail-closed and covers a mid-session policy flip, not just fresh logins. The
        # totp read is skipped entirely unless the org requires 2FA (backward-compat:
        # no org / no requirement -> unchanged today's behaviour). The 2FA REQUIREMENT
        # is the ACTIVE org's policy; the FACTOR travels with the identity, so it is
        # read at the identity realm (tenant_id), rebinding the RLS tenant around that
        # one realm-scoped read then restoring the active org ([2026] VJS-COUNTY 11, D5).
        org = await store.get_org(active_org_id)
        if org is not None and org.require_two_factor:
            set_current_tenant(tenant_id)
            totp = await store.get_user_totp(tenant_id, user.id)
            set_current_tenant(active_org_id)
            if not (totp and totp.enrolled) and (
                request.url.path not in _ENROLLMENT_ONLY_ALLOWED
            ):
                raise HTTPException(
                    status_code=403, detail="two_factor_enrollment_required"
                )

        # Active workspace ([2026] VJS-COUNTY 8, D4): RE-AUTHORIZE the session's
        # persisted active workspace against CURRENT membership every request, WITHIN
        # the active org (D3). A revoked membership (or a deleted workspace, or a
        # workspace in a different org than the active one) drops to None here, fail-
        # closed, so the kernel never carries a stale or cross-org workspace scope.
        active_workspace_id = await resolve_active_workspace(
            store, active_org_id, user.id, session.active_workspace_id
        )

        # Grant resolution ([2026] VJS-COUNTY 8, D11): the caller's org/user grants,
        # NARROWED by the active workspace role's ceiling when (and only when) the
        # caller is a member of an active workspace. No active workspace -> today's
        # grants, unchanged (backward-compat). The narrowing can only intersect DOWN,
        # never widen (COUNTY 5). Computed ONCE here; the GrantChecker chokepoint then
        # enforces these effective grants unchanged (no workspace logic in the routes).
        grants = await effective_grants_for_request(store, user, active_workspace_id)

        # Leave the RLS tenant bound to the ACTIVE org for the rest of the request
        # (D3: exactly ONE active tenant). The Principal's tenant_id IS the active org,
        # so every downstream store read/write + the GrantChecker chokepoint are scoped
        # to it - a cross-org read is impossible.
        set_current_tenant(active_org_id)
        request.state.boltrig_session = session
        return Principal(
            tenant_id=active_org_id,
            subject=user.id,
            grants=grants,
            role=user.role,
            actor_tier="human",
            scope=user.scope,
            active_workspace_id=active_workspace_id,
            # A first-party interactive login: a person authenticated at the door
            # with a password (and a second factor where the org requires one).
            credential_kind="session",
        )

    return resolver
