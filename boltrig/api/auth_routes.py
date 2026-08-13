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

from boltrig.api import desktop_session_auth
from boltrig.config import load_settings
from boltrig.identity import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    hash_password,
    new_session,
    pick_default_org,
    pick_default_workspace,
    rotate_session,
    validate_password_strength,
    verify_dummy,
    verify_password,
)
from boltrig.identity.invites import hash_invite_token
from boltrig.identity.passwords import WeakPassword
from boltrig.kernel.web_security import client_ip as _client_ip
from boltrig.identity.totp import (
    CHALLENGE_TTL,
    generate_challenge_token,
    generate_recovery_codes,
    generate_totp_secret,
    hash_challenge_token,
    hash_recovery_code,
    totp_provisioning_uri,
    verify_totp,
    verify_totp_dummy,
)
from boltrig.models import (
    ActionType,
    AuditEvent,
    RateLimited,
    SecurityEventType,
    TwoFactorChallenge,
    User,
    UserTotp,
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

# Second-factor challenge rate limits ([2026] VJS-COUNTY 10, D5), same shape as the
# login bounds: a tight per-identity bound (a targeted code-guess) and a broad per-IP
# bound (spraying). Both are fixed-window, keyed by a distinct verb id.
_TFA_RL_IDENTITY = RateLimit(per="minute", max=5, scope="verb")
_TFA_RL_IP = RateLimit(per="minute", max=30, scope="verb")

# The one generic second-factor failure (byte-identical for a wrong code, an unknown
# or expired challenge, and a used/absent recovery code) so nothing enumerates state.
_GENERIC_2FA_FAILURE = {"status": "error", "reason": "invalid or expired code"}


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
        User,
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
            # A USABLE login in the provisioned org ([2026] VJS-COUNTY 11, D4): the
            # invitee needs a per-org User row here (their identity + role/scope in the
            # new org) AND the org membership, so they can actually log in / switch into
            # it. The shared credential is already held once at the identity realm (set
            # in accept-invite), so no per-org credential is created - it is ASSOCIATED
            # via the email that keys both. Without this User row the resolver would
            # read no per-org identity for the new org and fail closed; before this fix
            # accept created only the OrgMember (no usable login). Owner of their own
            # provisioned org -> superadmin, all-authority scope (mirrors `initiate`).
            await k.store.upsert_user(User(
                id=email, tenant_id=new_tid, email=email, role="superadmin",
                scope={"all": True}, status="active", source="invitation",
                last_seen_at=utcnow(),
            ))
            # add_org_member also records the email -> orgs index pointer (D1), so login
            # discovers the new org and the switch can re-authorize it against org_members.
            await k.store.add_org_member(OrgMember(
                user_id=email, tenant_id=new_tid, role="superadmin",
            ))
        finally:
            set_current_tenant(inv.tenant_id)
        summary["provisioned_org"] = new_tid
    return summary


def _set_session_cookies(
    resp: JSONResponse,
    secret: str,
    csrf: str,
    *,
    request: Request | None = None,
) -> None:
    """Set the httpOnly+Secure+SameSite session cookie and the readable CSRF cookie.

    The session cookie is httpOnly (JS cannot read it), Secure (HTTPS only) and
    SameSite=Strict for the hosted web app. An explicitly CORS-allowlisted
    packaged Tauri origin receives SameSite=None; CSRF remains mandatory.
    """
    secure = _cookie_secure()
    desktop_session_auth.set_session_cookies(
        resp, secret, csrf, secure=secure, request=request,
    )


async def _mint_web_session(k, tenant: str, user: User):
    """Mint + persist a fresh web session for ``user`` and seed its active workspace.

    Shared by the plain login path, the org-required enrollment path, and the 2FA
    challenge-pass path so the session is issued identically wherever the second
    factor (or its absence) has been satisfied. Returns ``(secret, csrf)`` for the
    caller to cookie; only the hash is persisted (D2/D6).
    """
    from boltrig.store.postgres import set_current_tenant

    session, secret, csrf = new_session(tenant, user.id, client="web")
    # Seed the deterministic default ACTIVE ORG from the global email -> orgs index
    # ([2026] VJS-COUNTY 11, D2). None for a legacy / single-org identity (no index
    # rows), where the resolver falls back to the session's own tenant. The resolver
    # RE-AUTHORIZES this every request against org_members (fail-closed), so it is only
    # a hint. The default active WORKSPACE is then seeded from membership WITHIN that
    # active org (or the session's own tenant when there is no distinct active org).
    orgs = await k.store.list_orgs_for_email(user.id)
    session.active_org_id = pick_default_org(orgs)
    ws_tenant = session.active_org_id or tenant
    # The workspace read must be scoped to the ACTIVE org, not the identity realm: for
    # a cross-org login (active org != realm) reading it under the realm GUC would,
    # under live RLS, intersect to zero rows and seed no default workspace. Bind the
    # active-org tenant for the read, then restore the realm for the session write
    # (the session lives at the identity realm).
    if ws_tenant != tenant:
        set_current_tenant(ws_tenant)
    workspaces = await k.store.list_workspaces_for_user(ws_tenant, user.id)
    if ws_tenant != tenant:
        set_current_tenant(tenant)
    session.active_workspace_id = pick_default_workspace(workspaces)
    await k.store.add_session(session)
    return session, secret, csrf


def _session_response(secret: str, csrf: str, user: User, *,
                      request: Request | None = None, status: str = "ok",
                      extra: dict | None = None) -> JSONResponse:
    """The login/challenge success envelope + the session cookies. ``status`` is
    "ok" for a fully-authenticated session, "2fa_enrollment_required" for an org-
    required enrollment-only session, or "password_change_required" for an account
    still holding its provisioning credential. The resolver clamps the latter two."""
    body = {
        "status": status,
        "csrf_token": csrf,
        "user": {"id": user.id, "email": user.email, "role": user.role},
    }
    if extra:
        body.update(extra)
    resp = JSONResponse(body)
    _set_session_cookies(resp, secret, csrf, request=request)
    return resp


async def _load_totp_secret(k, tenant: str, secret_ref: str | None) -> str | None:
    """Load the SEALED base32 TOTP secret for a ref, kernel-side, at verify time.

    Reads the RLS-fenced ``credential_refs`` seam (the same sealed store the channel
    signing secret + per-org AI keys use). The secret is never logged, returned, or
    written to audit - it is handed straight to :func:`verify_totp`."""
    if not secret_ref:
        return None
    ref = await k.store.get_credential_ref(tenant, secret_ref)
    return (ref or {}).get("secret") if ref else None


async def _verify_second_factor(
    k, tenant: str, user_id: str, secret: str | None, code: str
) -> tuple[str | None, bool]:
    """Verify a presented second factor: a TOTP code first, else a one-time recovery
    code (D2 fallback, single-use). Returns ``(method, ok)`` where method is 'totp' /
    'recovery' / None. Constant-time: a TOTP verify is ALWAYS spent before the
    recovery fallback, so timing carries no oracle (D5). The recovery code is consumed
    ATOMICALLY (single-use) - a used or absent code fails."""
    if verify_totp(secret, code):
        return ("totp", True)
    if await k.store.consume_recovery_code(tenant, user_id, hash_recovery_code(code)):
        return ("recovery", True)
    return (None, False)


async def _two_factor_state(k, tenant: str, user: User) -> tuple[bool, bool]:
    """Return ``(second_factor_due, enrolled)`` for ``user`` after a password verify.

    ``second_factor_due`` is True when the user has 2FA enrolled OR the org requires
    it (D3). ``enrolled`` is True only when the user has an ACTIVATED TOTP factor. The
    two together drive the login fork: enrolled -> challenge (no session); due but not
    enrolled -> forced enrollment (D4); neither -> a plain session (unchanged)."""
    totp = await k.store.get_user_totp(tenant, user.id)
    enrolled = bool(totp and totp.enrolled)
    org = await k.store.get_org(tenant)
    org_requires = bool(org and org.require_two_factor)
    return (enrolled or org_requires, enrolled)


def register_auth_routes(app, *, principal_dep, get_kernel) -> None:
    K = Depends(get_kernel)
    P = Depends(principal_dep)

    desktop_session_auth.register_auth_support_routes(app, principal_dep, get_kernel)

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
        # Argon2 work is pure and may fail only before the one-time bearer is
        # claimed.  Once claimed, no concurrent/replayed request may reach a
        # password or provisioning write, even if later operational work fails.
        password_hash = hash_password(password)

        tenant = _console_tenant()
        set_current_tenant(tenant)  # bind before any RLS-scoped read/write
        # One generic rejection for unknown / expired / already-used, so a probe
        # cannot distinguish them.
        invalid = JSONResponse(
            {"status": "error", "reason": "invalid or expired invite"}, status_code=400
        )
        inv = await k.store.claim_invitation_by_token_hash(
            tenant, hash_invite_token(token), utcnow()
        )
        if inv is None:
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
        # Store ONLY the argon2id hash, apart from the identity row (D4). The SHARED
        # credential is held ONCE at the identity realm (``tenant`` == _console_tenant(),
        # the login realm), keyed by the normalised email - never duplicated per org
        # ([2026] VJS-COUNTY 11, D1/D5). Every org this identity belongs to authenticates
        # against this one credential; the invite's own tenant is the realm here
        # (invites are consumed at the login realm), so this is the identity home.
        await k.store.set_password_credential(
            tenant, email, password_hash
        )
        # Org/workspace-scoped seating + provisioning ([2026] VJS-COUNTY 8, D6). Each
        # arm runs only when its intent is present on the invite (a legacy invite
        # carries none and behaves exactly as before). The invite's authority was
        # already bounded at CREATION (the create-invite route re-checked the inviter
        # could manage a targeted workspace and gated org provisioning to superadmin),
        # so accept just materialises what was authorised.
        seated = await _seat_invitee(k, inv, email)
        # Keys-only via `_audit`: invitation id + email, never the password (SEC-191).
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
        # lever and useless anti-spray). The shared helper honors CF's
        # authoritative client header ONLY behind the BOLTRIG_TRUST_CF_CONNECTING_IP
        # opt-in (there CF sets it and strips any client-supplied copy); otherwise
        # the TCP peer. X-Forwarded-For is deliberately NOT trusted (spoofable
        # unless behind a known trusted proxy).
        client_ip = _client_ip(request) or "unknown"
        user_agent = request.headers.get("user-agent") or None
        try:
            # Enforce BOTH bounds before touching the credential store (D5).
            await k.rate_limiter.enforce(tenant, f"auth.login.ip:{client_ip}", _LOGIN_RL_IP)
            await k.rate_limiter.enforce(
                tenant, f"auth.login.id:{email}", _LOGIN_RL_IDENTITY
            )
        except RateLimited:
            # [2026] VJS-COUNTY 9, D3: a login throttle trip is a security signal on
            # the distinct stream, same keys-only dict discipline as `_audit`: email, never a secret.
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

        # Second-factor fork ([2026] VJS-COUNTY 10, D3/D4). The password verified;
        # decide whether a session may issue now.
        second_factor_due, enrolled = await _two_factor_state(k, tenant, user)
        if enrolled:
            # D3, FAIL-CLOSED: DO NOT issue a session. Mint a short-lived, single-use
            # challenge (the password is proven; the second factor is not) and return
            # a 2fa_required state. The follow-up /v1/auth/2fa/challenge issues the
            # session only once a TOTP or recovery code verifies against this.
            challenge = generate_challenge_token()
            await k.store.add_two_factor_challenge(TwoFactorChallenge(
                tenant_id=tenant, token_hash=hash_challenge_token(challenge),
                user_id=user.id, expires_at=utcnow() + CHALLENGE_TTL,
            ))
            # Keys-only via `_audit`: the fact of the challenge; the token is absent below (SEC-191).
            await _audit(k, tenant, user.id, "auth.2fa.challenge",
                         {"outcome": "challenge_issued"})
            return JSONResponse({"status": "2fa_required", "challenge_token": challenge})
        if second_factor_due:
            # D4: the org requires 2FA but the user has not enrolled. Issue an
            # ENROLLMENT-ONLY session (the resolver clamps it to the enroll surface
            # only) so the ONLY thing they can reach is enrollment. No console access.
            _, secret, csrf = await _mint_web_session(k, tenant, user)
            await _audit(k, tenant, user.id, "auth.login",
                         {"outcome": "2fa_enrollment_required"})
            return _session_response(secret, csrf, user, request=request,
                                     status="2fa_enrollment_required")

        # No second factor due: a plain session, exactly as before (backward-compat).
        session, secret, csrf = await _mint_web_session(k, tenant, user)
        # Keys-only via `_audit`: the session id, never the secret / csrf / password (D8, SEC-191).
        await _audit(k, tenant, user.id, "auth.login",
                     {"session_id": session.id, "outcome": "ok"})
        # D7: the session IS issued and the resolver clamps it. Saying so here lets
        # a console route straight to the rotation screen rather than discover the
        # clamp by being refused. Same shape as 2fa_enrollment_required above.
        clamped = "password_change_required" if user.must_change_password else "ok"
        return _session_response(secret, csrf, user, request=request, status=clamped)

    @app.post("/v1/auth/logout")
    async def logout(request: Request, k=K, p=P) -> JSONResponse:
        # D2: a logout revokes the session in the store (it stops resolving at
        # once). Requires an authenticated session; the CSRF check on this mutating
        # request is enforced by the session resolver.
        from boltrig.store.postgres import set_current_tenant

        session = getattr(request.state, "boltrig_session", None)
        resp = JSONResponse({"status": "ok"})
        if session is not None:
            session.revoked = True
            # A session lives at the identity realm (session.tenant_id), which differs
            # from the ACTIVE org (p.tenant_id) for a multi-org identity
            # ([2026] VJS-COUNTY 11). Bind the realm for the RLS-scoped write so the revoke
            # lands, then restore the active tenant for the audit.
            set_current_tenant(session.tenant_id)
            await k.store.update_session(session)
            set_current_tenant(p.tenant_id)
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
        from boltrig.store.postgres import set_current_tenant

        session = getattr(request.state, "boltrig_session", None)
        if session is None:
            return JSONResponse({"status": "error", "reason": "no session"},
                                status_code=401)
        try:
            session, secret, csrf = rotate_session(session)
        except ValueError:
            # Past the absolute lifetime cap: revoke and force re-authentication. The
            # session lives at the identity realm, so bind it for the RLS-scoped write
            # ([2026] VJS-COUNTY 11), then restore the active tenant.
            session.revoked = True
            set_current_tenant(session.tenant_id)
            await k.store.update_session(session)
            set_current_tenant(p.tenant_id)
            resp = JSONResponse({"status": "error", "reason": "session expired"},
                                status_code=401)
            resp.delete_cookie(SESSION_COOKIE, path="/")
            resp.delete_cookie(CSRF_COOKIE, path="/")
            return resp
        # Bind the identity realm for the RLS-scoped session write, then restore the
        # active tenant for the audit (the session lives at the realm, not the active
        # org, for a multi-org identity).
        set_current_tenant(session.tenant_id)
        await k.store.update_session(session)
        set_current_tenant(p.tenant_id)
        await _audit(k, p.tenant_id, p.subject, "auth.session.rotate",
                     {"session_id": session.id})
        resp = JSONResponse({"status": "ok", "csrf_token": csrf})
        _set_session_cookies(resp, secret, csrf, request=request)
        return resp

    # === TOTP two-factor ([2026] VJS-COUNTY 10) ==============================
    @app.post("/v1/auth/2fa/enroll")
    async def two_factor_enroll(request: Request, k=K, p=P) -> JSONResponse:
        # D1: begin enrollment. Mint a fresh TOTP secret, SEAL it in the credential
        # store (never a plaintext column), and return the otpauth URI + secret + the
        # one-time recovery codes EXACTLY ONCE (for the QR + the user to save). The
        # factor is not active until verify-enroll confirms a code (enrolled stays
        # false). Reachable by an enrollment-only session (it is on the resolver's
        # allowlist), so an org-required user can complete forced enrollment (D4).
        import uuid

        from boltrig.store.postgres import set_current_tenant

        # 2FA travels with the IDENTITY, not the per-org row ([2026] VJS-COUNTY 11, D5):
        # the enrolment + sealed secret + recovery codes live at the identity realm (the
        # login realm), keyed by the email (p.subject), so the ONE factor is checked once
        # at login regardless of which org is active. p.tenant_id is the ACTIVE org, so it
        # must NOT be used for 2FA storage.
        tenant = _console_tenant()
        set_current_tenant(tenant)
        # Rate-limit the begin (like verify-enroll/challenge/disable): each call mints
        # + seals a fresh secret and rotates the recovery codes, so an unrated begin
        # lets an authenticated user spam sealed-secret rows and silently invalidate
        # previously-shown codes. Bound per-identity + per-IP (CF-Connecting-IP only
        # behind the tunnel opt-in, never the spoofable XFF).
        client_ip = _client_ip(request) or "unknown"
        try:
            await k.rate_limiter.enforce(
                tenant, f"auth.2fa.enroll-begin.ip:{client_ip}", _TFA_RL_IP
            )
            await k.rate_limiter.enforce(
                tenant, f"auth.2fa.enroll-begin.id:{p.subject}", _TFA_RL_IDENTITY
            )
        except RateLimited:
            return JSONResponse({"status": "error", "reason": "too many attempts"},
                                status_code=429)
        existing = await k.store.get_user_totp(tenant, p.subject)
        if existing is not None and existing.enrolled:
            # Already enabled: re-enrolling would silently drop a working factor
            # without a fresh factor (a bypass). Require disable-then-enroll instead.
            return JSONResponse(
                {"status": "error", "reason": "two-factor is already enabled"},
                status_code=400,
            )
        secret = generate_totp_secret()
        secret_ref = f"cred_totp_{uuid.uuid4().hex[:16]}"
        # SEALED at rest (D1): the base32 secret lives only in the RLS-fenced
        # credential_refs seam, referenced by secret_ref on the user_totp row.
        await k.store.set_credential_ref(tenant, secret_ref, {"secret": secret})
        await k.store.set_user_totp(UserTotp(
            tenant_id=tenant, user_id=p.subject, secret_ref=secret_ref, enrolled=False,
        ))
        codes = generate_recovery_codes()
        # D2: persist ONLY the hashes; the plaintext codes leave in this response once.
        await k.store.set_recovery_codes(
            tenant, p.subject, [hash_recovery_code(c) for c in codes]
        )
        user = await k.store.get_user(tenant, p.subject)
        account = (user.email if user and user.email else p.subject)
        uri = totp_provisioning_uri(secret, account)
        # Keys-only via `_audit` (D5): enrollment-begin only, NEVER the secret, the otpauth
        # URI (which CONTAINS it) or the recovery codes (SEC-191).
        await _audit(k, tenant, p.subject, "auth.2fa.enroll", {"outcome": "begin"})
        return JSONResponse({
            "status": "ok",
            "otpauth_uri": uri,
            "secret": secret,
            "recovery_codes": codes,
        })

    @app.post("/v1/auth/2fa/verify-enroll")
    async def two_factor_verify_enroll(body: dict, request: Request, k=K, p=P) -> JSONResponse:
        # D3: confirm a code to ACTIVATE the pending enrollment (enrolled -> true).
        # Rate-limited + constant-time + audited (D5). Once active, an enrollment-only
        # session becomes fully privileged (the resolver re-derives on the next req).
        from boltrig.store.postgres import set_current_tenant

        # 2FA travels with the IDENTITY (the login realm), keyed by the email - never
        # the ACTIVE org (p.tenant_id) ([2026] VJS-COUNTY 11, D5).
        tenant = _console_tenant()
        set_current_tenant(tenant)
        code = body.get("code")
        code = code if isinstance(code, str) else ""
        client_ip = _client_ip(request) or "unknown"
        user_agent = request.headers.get("user-agent") or None
        try:
            await k.rate_limiter.enforce(tenant, f"auth.2fa.enroll.ip:{client_ip}", _TFA_RL_IP)
            await k.rate_limiter.enforce(
                tenant, f"auth.2fa.enroll.id:{p.subject}", _TFA_RL_IDENTITY
            )
        except RateLimited:
            await k.security.record(
                tenant, SecurityEventType.RATE_LIMIT_TRIP, "two_factor_rate_limited",
                actor=p.subject, actor_tier="human",
                ip_address=client_ip, user_agent=user_agent, resource="auth.2fa.verify_enroll",
            )
            return JSONResponse({"status": "error", "reason": "too many attempts"},
                                status_code=429)

        totp = await k.store.get_user_totp(tenant, p.subject)
        secret = await _load_totp_secret(k, tenant, totp.secret_ref if totp else None)
        if not totp or not secret:
            # Nothing pending: still spend a verify so timing carries no state oracle.
            verify_totp_dummy(code)
            return JSONResponse(_GENERIC_2FA_FAILURE, status_code=400)
        # Only a TOTP code activates enrollment (a recovery code cannot bootstrap it).
        if verify_totp(secret, code):
            totp.enrolled = True
            await k.store.set_user_totp(totp)
            await _audit(k, tenant, p.subject, "auth.2fa.verify_enroll",
                         {"outcome": "activated"})
            remaining = await k.store.count_active_recovery_codes(tenant, p.subject)
            return JSONResponse({"status": "ok", "recovery_codes_remaining": remaining})
        await _audit(k, tenant, p.subject, "auth.2fa.verify_enroll",
                     {"outcome": "rejected"}, status="denied")
        await k.security.record(
            tenant, SecurityEventType.LOGIN_FAILURE, "two_factor_verify_failed",
            actor=p.subject, actor_tier="human",
            ip_address=client_ip, user_agent=user_agent, resource="auth.2fa.verify_enroll",
        )
        return JSONResponse(_GENERIC_2FA_FAILURE, status_code=401)

    @app.post("/v1/auth/2fa/challenge")
    async def two_factor_challenge(body: dict, request: Request, k=K) -> JSONResponse:
        # D3, the login second-factor gate. PUBLIC (the challenge token IS the bearer,
        # like accept-invite): a valid challenge_token + a valid TOTP-or-recovery code
        # issues the session that /v1/auth/login withheld. Rate-limited + constant-time
        # + non-enumerating + fail-closed (an unknown/expired challenge or a bad code
        # returns one generic failure). The challenge is single-use (consumed on pass).
        from boltrig.store.postgres import set_current_tenant

        tenant = _console_tenant()
        set_current_tenant(tenant)
        token = body.get("challenge_token")
        token = token if isinstance(token, str) else ""
        code = body.get("code")
        code = code if isinstance(code, str) else ""
        client_ip = _client_ip(request) or "unknown"
        user_agent = request.headers.get("user-agent") or None

        # D5: the broad per-IP bound first, before any store/crypto work.
        try:
            await k.rate_limiter.enforce(tenant, f"auth.2fa.challenge.ip:{client_ip}", _TFA_RL_IP)
        except RateLimited:
            await k.security.record(
                tenant, SecurityEventType.RATE_LIMIT_TRIP, "two_factor_rate_limited",
                actor="unknown", actor_tier="human",
                ip_address=client_ip, user_agent=user_agent, resource="auth.2fa.challenge",
            )
            return JSONResponse({"status": "error", "reason": "too many attempts"},
                                status_code=429)

        challenge = await k.store.get_two_factor_challenge(
            tenant, hash_challenge_token(token)
        ) if token else None
        expired = (
            challenge is not None and challenge.expires_at is not None
            and challenge.expires_at <= utcnow()
        )
        if challenge is None or expired:
            # Fail-closed + constant-time: spend a verify against the decoy so an
            # invalid/expired challenge is indistinguishable from a wrong code.
            verify_totp_dummy(code)
            return JSONResponse(_GENERIC_2FA_FAILURE, status_code=401)

        # The tight per-identity bound, now that the challenge names the user.
        try:
            await k.rate_limiter.enforce(
                tenant, f"auth.2fa.challenge.id:{challenge.user_id}", _TFA_RL_IDENTITY
            )
        except RateLimited:
            await k.security.record(
                tenant, SecurityEventType.RATE_LIMIT_TRIP, "two_factor_rate_limited",
                actor=challenge.user_id, actor_tier="human",
                ip_address=client_ip, user_agent=user_agent, resource="auth.2fa.challenge",
            )
            return JSONResponse({"status": "error", "reason": "too many attempts"},
                                status_code=429)

        user = await k.store.get_user(tenant, challenge.user_id)
        totp = await k.store.get_user_totp(tenant, challenge.user_id)
        secret = await _load_totp_secret(k, tenant, totp.secret_ref if totp else None)
        # Fail-closed if the user is gone/deactivated or the factor is not active.
        if user is None or user.status != "active" or not totp or not totp.enrolled or not secret:
            verify_totp_dummy(code)
            return JSONResponse(_GENERIC_2FA_FAILURE, status_code=401)

        method, ok = await _verify_second_factor(k, tenant, challenge.user_id, secret, code)
        if not ok:
            # DO NOT consume the challenge on a miss (retry allowed within TTL + the
            # rate-limit budget). Audit + security-signal, keys-only.
            await _audit(k, tenant, challenge.user_id, "auth.2fa.challenge",
                         {"outcome": "rejected"}, status="denied")
            await k.security.record(
                tenant, SecurityEventType.LOGIN_FAILURE, "two_factor_challenge_failed",
                actor=challenge.user_id, actor_tier="human",
                ip_address=client_ip, user_agent=user_agent, resource="auth.2fa.challenge",
            )
            return JSONResponse(_GENERIC_2FA_FAILURE, status_code=401)

        # Single-use: consume the challenge; a lost race (already consumed) fails.
        if not await k.store.consume_two_factor_challenge(tenant, challenge.token_hash):
            return JSONResponse(_GENERIC_2FA_FAILURE, status_code=401)
        session, secret_cookie, csrf = await _mint_web_session(k, tenant, user)
        await _audit(k, tenant, user.id, "auth.2fa.challenge",
                     {"session_id": session.id, "outcome": "ok", "method": method})
        if method == "recovery":
            # A recovery code was spent (single-use). Audit the USE keys-only so the
            # burn-down is visible; never the code.
            remaining = await k.store.count_active_recovery_codes(tenant, user.id)
            await _audit(k, tenant, user.id, "auth.2fa.recovery_used",
                         {"outcome": "consumed", "recovery_codes_remaining": remaining})
        return _session_response(secret_cookie, csrf, user, request=request)

    @app.post("/v1/auth/2fa/disable")
    async def two_factor_disable(body: dict, request: Request, k=K, p=P) -> JSONResponse:
        # Self-disable, requires a FRESH factor (a current TOTP or a recovery code) -
        # never a bypass. Removes the enrollment, the sealed secret, and the recovery
        # codes. Rate-limited + constant-time + audited (D5). If the org still requires
        # 2FA, the resolver re-clamps the caller to enrollment-only next request (they
        # cannot escape the requirement; they simply reset).
        from boltrig.store.postgres import set_current_tenant

        # 2FA travels with the IDENTITY (the login realm), keyed by the email - never
        # the ACTIVE org (p.tenant_id) ([2026] VJS-COUNTY 11, D5).
        tenant = _console_tenant()
        set_current_tenant(tenant)
        code = body.get("code")
        code = code if isinstance(code, str) else ""
        client_ip = _client_ip(request) or "unknown"
        user_agent = request.headers.get("user-agent") or None
        try:
            await k.rate_limiter.enforce(tenant, f"auth.2fa.disable.ip:{client_ip}", _TFA_RL_IP)
            await k.rate_limiter.enforce(
                tenant, f"auth.2fa.disable.id:{p.subject}", _TFA_RL_IDENTITY
            )
        except RateLimited:
            await k.security.record(
                tenant, SecurityEventType.RATE_LIMIT_TRIP, "two_factor_rate_limited",
                actor=p.subject, actor_tier="human",
                ip_address=client_ip, user_agent=user_agent, resource="auth.2fa.disable",
            )
            return JSONResponse({"status": "error", "reason": "too many attempts"},
                                status_code=429)

        totp = await k.store.get_user_totp(tenant, p.subject)
        secret = await _load_totp_secret(k, tenant, totp.secret_ref if totp else None)
        if not totp or not totp.enrolled or not secret:
            verify_totp_dummy(code)
            return JSONResponse(
                {"status": "error", "reason": "two-factor is not enabled"}, status_code=400
            )
        method, ok = await _verify_second_factor(k, tenant, p.subject, secret, code)
        if not ok:
            await _audit(k, tenant, p.subject, "auth.2fa.disable",
                         {"outcome": "rejected"}, status="denied")
            await k.security.record(
                tenant, SecurityEventType.LOGIN_FAILURE, "two_factor_disable_failed",
                actor=p.subject, actor_tier="human",
                ip_address=client_ip, user_agent=user_agent, resource="auth.2fa.disable",
            )
            return JSONResponse(_GENERIC_2FA_FAILURE, status_code=401)
        # Tear down the factor: drop the enrollment, clear the recovery codes, and
        # overwrite the sealed secret material (so nothing reusable is left at rest).
        await k.store.delete_user_totp(tenant, p.subject)
        await k.store.clear_recovery_codes(tenant, p.subject)
        await k.store.set_credential_ref(tenant, totp.secret_ref, {})
        await _audit(k, tenant, p.subject, "auth.2fa.disable",
                     {"outcome": "disabled", "method": method})
        return JSONResponse({"status": "ok"})
