"""First-party invite-only login HTTP surface ([2026] VJS-COUNTY 7).

The sole internet-facing gate when auth_mode=session: accept-invite (consume a
single-use hashed invite token + set a password, D1), login (email/password ->
a Boltrig session cookie, D2/D5), logout (revoke the session, D2), and refresh
(rotate the session secret, D6). There is NO open self-signup: an account exists
only by consuming an admin-created invitation.

These routes are thin over the Store + identity helpers; they add no dispatch
policy (the kernel chokepoint is unchanged). Login is rate-limited through the
existing RateLimiter, verifies in constant time (a dummy hash on the absent-user
path), and returns a GENERIC failure that never reveals whether an email exists.
Every login / logout / accept / revoke is audited KEYS-ONLY: never the password
or the session secret (D8, K-20).
"""

from __future__ import annotations

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from boltrig.config import load_settings
from boltrig.identity import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    hash_password,
    new_session,
    pick_default_workspace,
    rotate_session,
    validate_password_strength,
    verify_dummy,
    verify_password,
)
from boltrig.identity.invites import hash_invite_token
from boltrig.identity.passwords import WeakPassword
from boltrig.identity.sessions import SESSION_TTL_HOURS
from boltrig.models import (
    ActionType,
    AuditEvent,
    RateLimited,
    SecurityEventType,
    User,
    utcnow,
)
from boltrig.models.registry import RateLimit

# Login rate limits enforced through the existing RateLimiter (D5). Per-identity
# is the tight bound (a targeted guess); per-IP is the broad bound (spraying many
# emails from one host). Both are fixed-window counters keyed by a distinct verb
# id, so an existing and a non-existent email are throttled identically (no oracle).
_LOGIN_RL_IDENTITY = RateLimit(per="minute", max=5, scope="verb")
_LOGIN_RL_IP = RateLimit(per="minute", max=30, scope="verb")

# The one generic login failure. It is byte-identical for a wrong password, an
# unknown email, and a deactivated user, so the response body never enumerates
# which emails exist (D5).
_GENERIC_LOGIN_FAILURE = {"status": "error", "reason": "invalid email or password"}


def _console_tenant() -> str:
    """The single-tenant console's tenant id (login/accept operate within it)."""
    return load_settings().session_tenant or "default"


def _cookie_secure() -> bool:
    return load_settings().session_cookie_secure


def _norm_email(raw) -> str:
    return raw.strip().lower() if isinstance(raw, str) else ""


async def _audit(kernel, tenant_id, actor, verb, detail, status="ok") -> None:
    await kernel.audit.write(
        AuditEvent(
            tenant_id=tenant_id, ts=utcnow(), actor=actor, actor_tier="human",
            action_type=ActionType.TOOL_CALL, verb=verb, status=status, detail=detail,
        )
    )


def _ws_slug(name: str) -> str:
    """A globally-unique url-safe slug for a provisioned workspace."""
    import uuid

    from boltrig.identity.tenancy import default_org_slug

    return f"{default_org_slug(name) or 'workspace'}-{uuid.uuid4().hex[:6]}"


async def _seat_invitee(k, inv, email: str) -> dict:
    """Materialise an org/workspace-scoped invite's provisioning on accept ([2026]
    VJS-COUNTY 8, D6). Returns a small keys-only summary for the audit row. Each arm
    fires only when its intent is present; the authority was bounded at invite
    CREATION, so nothing here is a fresh grant decision.

      - workspace_id       : seat the invitee into an EXISTING workspace as a member
                             with the invited role (coerced into WORKSPACE_ROLES,
                             defaulting to 'member' when the platform role is not a
                             workspace role - never above the ceiling).
      - provision_workspace: CREATE that workspace and seat the invitee as its OWNER.
      - provision_org      : provision a brand-new org (a fresh tenant_id) and seat
                             the invitee as its owner. RLS is bound to the new tenant
                             around those writes, then the console tenant is restored.
    """
    import uuid

    from boltrig.models import (
        WORKSPACE_ROLES,
        OrgMember,
        Organisation,
        Workspace,
        WorkspaceMember,
    )
    from boltrig.store.postgres import set_current_tenant

    summary: dict = {}
    if inv.workspace_id:
        role = inv.intended_role if inv.intended_role in WORKSPACE_ROLES else "member"
        await k.store.add_workspace_member(WorkspaceMember(
            user_id=email, workspace_id=inv.workspace_id, tenant_id=inv.tenant_id, role=role,
        ))
        summary["seated_workspace"] = inv.workspace_id
    if inv.provision_workspace_name:
        ws = Workspace(
            id=uuid.uuid4().hex, tenant_id=inv.tenant_id,
            name=inv.provision_workspace_name, slug=_ws_slug(inv.provision_workspace_name),
        )
        await k.store.create_workspace(ws)
        await k.store.add_workspace_member(WorkspaceMember(
            user_id=email, workspace_id=ws.id, tenant_id=inv.tenant_id, role="owner",
        ))
        summary["provisioned_workspace"] = ws.id
    if inv.provision_org_name:
        # A fresh org == a fresh tenant_id (the org id IS the tenant boundary, D1).
        # Bind RLS to the new tenant for its writes, then restore the console tenant.
        new_tid = uuid.uuid4().hex
        set_current_tenant(new_tid)
        try:
            await k.store.create_org(Organisation(
                id=new_tid, name=inv.provision_org_name,
                slug=f"{new_tid[:8]}-org",
            ))
            await k.store.add_org_member(OrgMember(
                user_id=email, tenant_id=new_tid, role="superadmin",
            ))
        finally:
            set_current_tenant(inv.tenant_id)
        summary["provisioned_org"] = new_tid
    return summary


def _set_session_cookies(resp: JSONResponse, secret: str, csrf: str) -> None:
    """Set the httpOnly+Secure+SameSite session cookie and the readable CSRF cookie.

    The session cookie is httpOnly (JS cannot read it), Secure (HTTPS only) and
    SameSite=Strict (never sent on a cross-site request) - so it is not exposed to
    XSS exfiltration or CSRF (D6). The CSRF cookie is deliberately readable by JS so
    the SPA can echo it in the X-Boltrig-CSRF header (the double-submit half).
    """
    secure = _cookie_secure()
    max_age = SESSION_TTL_HOURS * 3600
    resp.set_cookie(
        SESSION_COOKIE, secret, max_age=max_age, httponly=True, secure=secure,
        samesite="strict", path="/",
    )
    resp.set_cookie(
        CSRF_COOKIE, csrf, max_age=max_age, httponly=False, secure=secure,
        samesite="strict", path="/",
    )


def register_auth_routes(app, *, principal_dep, get_kernel) -> None:
    K = Depends(get_kernel)
    P = Depends(principal_dep)

    @app.post("/v1/auth/accept-invite")
    async def accept_invite(body: dict, k=K) -> JSONResponse:
        # D1: consume a single-use, HASHED, EXPIRING invite token and set the
        # password. No open self-signup - the token must match a pending admin
        # invitation. Public (no principal): the token IS the bearer of authority.
        from boltrig.store.postgres import set_current_tenant

        token = body.get("token")
        password = body.get("password")
        if not isinstance(token, str) or not token:
            return JSONResponse({"status": "error", "reason": "token is required"},
                                status_code=400)
        try:
            validate_password_strength(password)
        except WeakPassword as exc:
            return JSONResponse({"status": "error", "reason": str(exc)}, status_code=400)

        tenant = _console_tenant()
        set_current_tenant(tenant)  # bind before any RLS-scoped read/write
        inv = await k.store.find_invitation_by_token_hash(tenant, hash_invite_token(token))
        # One generic rejection for unknown / expired / already-used, so a probe
        # cannot distinguish them.
        invalid = JSONResponse(
            {"status": "error", "reason": "invalid or expired invite"}, status_code=400
        )
        if inv is None:
            return invalid
        if inv.expires_at is not None and inv.expires_at <= utcnow():
            return invalid
        # Atomic single-use: only the winner proceeds (D1). A lost race / already
        # consumed token returns the same generic rejection.
        if not await k.store.consume_invitation(inv.tenant_id, inv.id):
            return invalid

        email = _norm_email(inv.email)
        existing = await k.store.get_user(inv.tenant_id, email)
        user = User(
            id=email,
            tenant_id=inv.tenant_id,
            email=email,
            display_name=existing.display_name if existing else None,
            role=inv.intended_role,
            scope=dict(inv.intended_scope or {}),
            status="active",
            source="invitation",
            last_seen_at=utcnow(),
            created_at=existing.created_at if existing else utcnow(),
        )
        await k.store.upsert_user(user)
        # Store ONLY the argon2id hash, apart from the identity row (D4).
        await k.store.set_password_credential(
            inv.tenant_id, email, hash_password(password)
        )
        # Org/workspace-scoped seating + provisioning ([2026] VJS-COUNTY 8, D6). Each
        # arm runs only when its intent is present on the invite (a legacy invite
        # carries none and behaves exactly as before). The invite's authority was
        # already bounded at CREATION (the create-invite route re-checked the inviter
        # could manage a targeted workspace and gated org provisioning to superadmin),
        # so accept just materialises what was authorised.
        seated = await _seat_invitee(k, inv, email)
        # Keys-only audit: the invitation id + email (identity), never the password.
        await _audit(k, inv.tenant_id, email, "auth.invite.accept",
                     {"invitation_id": inv.id, "email": email, **seated})
        return JSONResponse({"status": "ok", "email": email})

    @app.post("/v1/auth/login")
    async def login(body: dict, request: Request, k=K) -> JSONResponse:
        # D2/D5: verify email+password, issue a Boltrig session. Rate-limited
        # (per-identity + per-IP), constant-time, non-enumerating. Public.
        from boltrig.store.postgres import set_current_tenant

        email = _norm_email(body.get("email"))
        password = body.get("password")
        password = password if isinstance(password, str) else ""
        tenant = _console_tenant()
        set_current_tenant(tenant)

        # Behind the Cloudflare tunnel the TCP peer is the tunnel/loopback, so a
        # per-IP bound keyed on it collapses to ONE global bucket (a login-DoS
        # lever and useless anti-spray). Trust CF's authoritative client header
        # when present (CF sets it and strips any client-supplied copy); fall back
        # to the TCP peer off-tunnel. X-Forwarded-For is deliberately NOT trusted
        # (spoofable unless behind a known trusted proxy).
        client_ip = (
            request.headers.get("cf-connecting-ip")
            or (request.client.host if request.client else "unknown")
        )
        user_agent = request.headers.get("user-agent") or None
        try:
            # Enforce BOTH bounds before touching the credential store (D5).
            await k.rate_limiter.enforce(tenant, f"auth.login.ip:{client_ip}", _LOGIN_RL_IP)
            await k.rate_limiter.enforce(
                tenant, f"auth.login.id:{email}", _LOGIN_RL_IDENTITY
            )
        except RateLimited:
            # [2026] VJS-COUNTY 9, D3: a login throttle trip is a security signal on
            # the distinct stream (keys-only: the email is identity, never a secret).
            await k.security.record(
                tenant, SecurityEventType.RATE_LIMIT_TRIP, "login_rate_limited",
                actor=email or "unknown", actor_tier="human",
                ip_address=client_ip, user_agent=user_agent, resource="auth.login",
            )
            # Generic 429; identical whether or not the email exists.
            return JSONResponse({"status": "error", "reason": "too many attempts"},
                                status_code=429)

        user = await k.store.get_user(tenant, email) if email else None
        cred = await k.store.get_password_credential(tenant, email) if email else None
        # Constant-time: always spend an argon2 verify. On the absent/deactivated
        # path run the decoy so timing cannot reveal existence (D5).
        if user is not None and user.status == "active" and cred:
            ok = verify_password(cred, password)
        else:
            verify_dummy(password)
            ok = False
        if not ok:
            await _audit(k, tenant, email or "unknown", "auth.login",
                         {"email": email, "outcome": "rejected"}, status="denied")
            # [2026] VJS-COUNTY 9, D3: a login failure is a security signal on the
            # distinct stream, at the same field depth (ip/ua). Keys-only: never the
            # password (only the email, which is identity not a secret).
            await k.security.record(
                tenant, SecurityEventType.LOGIN_FAILURE, "invalid_email_or_password",
                actor=email or "unknown", actor_tier="human",
                ip_address=client_ip, user_agent=user_agent, resource="auth.login",
            )
            return JSONResponse(_GENERIC_LOGIN_FAILURE, status_code=401)

        session, secret, csrf = new_session(tenant, user.id, client="web")
        # Seed the session's default active workspace from membership ([2026] VJS-
        # COUNTY 8, D4): a deterministic pick of the user's workspaces, or None when
        # they belong to none yet. This is only a hint - the resolver re-authorizes
        # it against membership on every subsequent request (fail-closed).
        workspaces = await k.store.list_workspaces_for_user(tenant, user.id)
        session.active_workspace_id = pick_default_workspace(workspaces)
        await k.store.add_session(session)
        # Keys-only audit: the session id, never the secret / csrf / password (D8).
        await _audit(k, tenant, user.id, "auth.login",
                     {"session_id": session.id, "outcome": "ok"})
        resp = JSONResponse({
            "status": "ok",
            "csrf_token": csrf,
            "user": {"id": user.id, "email": user.email, "role": user.role},
        })
        _set_session_cookies(resp, secret, csrf)
        return resp

    @app.post("/v1/auth/logout")
    async def logout(request: Request, k=K, p=P) -> JSONResponse:
        # D2: a logout revokes the session in the store (it stops resolving at
        # once). Requires an authenticated session; the CSRF check on this mutating
        # request is enforced by the session resolver.
        session = getattr(request.state, "boltrig_session", None)
        resp = JSONResponse({"status": "ok"})
        if session is not None:
            session.revoked = True
            await k.store.update_session(session)
            await _audit(k, p.tenant_id, p.subject, "auth.logout",
                         {"session_id": session.id})
        resp.delete_cookie(SESSION_COOKIE, path="/")
        resp.delete_cookie(CSRF_COOKIE, path="/")
        return resp

    @app.post("/v1/auth/refresh")
    async def refresh(request: Request, k=K, p=P) -> JSONResponse:
        # D6: rotate the session secret + CSRF token and extend the bounded expiry.
        # The OLD cookie stops resolving. Requires an authenticated session; CSRF is
        # enforced by the resolver on this mutating request.
        session = getattr(request.state, "boltrig_session", None)
        if session is None:
            return JSONResponse({"status": "error", "reason": "no session"},
                                status_code=401)
        try:
            session, secret, csrf = rotate_session(session)
        except ValueError:
            # Past the absolute lifetime cap: revoke and force re-authentication.
            session.revoked = True
            await k.store.update_session(session)
            resp = JSONResponse({"status": "error", "reason": "session expired"},
                                status_code=401)
            resp.delete_cookie(SESSION_COOKIE, path="/")
            resp.delete_cookie(CSRF_COOKIE, path="/")
            return resp
        await k.store.update_session(session)
        await _audit(k, p.tenant_id, p.subject, "auth.session.rotate",
                     {"session_id": session.id})
        resp = JSONResponse({"status": "ok", "csrf_token": csrf})
        _set_session_cookies(resp, secret, csrf)
        return resp
