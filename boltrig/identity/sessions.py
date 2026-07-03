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

from .provisioning import current_grants_for_user

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
        user = await store.get_user(session.tenant_id, session.user_id)
        if user is None or user.status != "active":
            # Deactivated / de-provisioned -> the session is dead (fail-closed, D3).
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

        request.state.boltrig_session = session
        return Principal(
            tenant_id=session.tenant_id,
            subject=user.id,
            grants=current_grants_for_user(user),
            role=user.role,
            actor_tier="human",
            scope=user.scope,
        )

    return resolver
