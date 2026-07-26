"""``POST /v1/auth/change-password`` - retire a credential you still hold.

Split out of ``auth_routes`` rather than added to it: that module was already at
its structural ratchet, and growing an 810-line file and a 503-line function to
carry one more route is how a module becomes unreadable one justified addition at
a time.

This is the way OUT of the forced-rotation clamp ([2026] VJS-COUNTY 8, D7), and
the reason that clamp is a finished feature rather than a lockout - without it the
founding operator seeded by ``boltrig initiate`` could reach only logout and would
have to return to a shell to make their own console usable.
"""

from __future__ import annotations

from dataclasses import replace as _replace

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from boltrig.identity import hash_password, validate_password_strength, verify_password
from boltrig.identity.passwords import WeakPassword
from boltrig.kernel.web_security import client_ip as _client_ip
from boltrig.models import RateLimited, SecurityEventType
from boltrig.models.registry import RateLimit


# Per-identity only. The per-IP bound belongs on the PUBLIC login surface; here the
# caller already holds a session, and this is a credential oracle if left unbounded.
_RL_IDENTITY = RateLimit(per="minute", max=5, scope="verb")


async def _verified_user(k, p, request, body, realm):
    """The caller, ONLY if they proved the credential they are asking to retire.

    A session is a bearer of identity, not proof of the credential, and this
    route's whole job is to retire a credential - so a stolen or borrowed session
    must not be able to set a new password and lock the owner out. The rate limit
    is per-identity for the same reason: unbounded, this is a credential oracle.
    """
    from boltrig.api.auth_routes import _audit

    user = await k.store.get_user(realm, p.subject)
    if user is None:
        return None, None
    try:
        await k.rate_limiter.enforce(
            realm, f"auth.change_password.id:{user.id}", _RL_IDENTITY
        )
    except RateLimited:
        return None, JSONResponse(
            {"status": "error", "reason": "too many attempts"}, status_code=429
        )
    current = body.get("current_password")
    cred = await k.store.get_password_credential(realm, user.id)
    if not (cred and verify_password(cred, current if isinstance(current, str) else "")):
        await _audit(k, realm, user.id, "auth.change_password",
                     {"outcome": "rejected"}, status="denied")
        await k.security.record(
            realm, SecurityEventType.LOGIN_FAILURE, "invalid_current_password",
            actor=user.id, actor_tier="human",
            ip_address=_client_ip(request) or "unknown",
            user_agent=request.headers.get("user-agent") or None,
            resource="auth.change_password",
        )
        return None, None
    return (user, cred), None


async def _rotate(k, request, body, realm, user, cred) -> JSONResponse:
    """Set the new credential, having established the caller holds the old one."""
    from boltrig.api.auth_routes import _audit

    new = body.get("new_password")
    new = new if isinstance(new, str) else ""
    try:
        validate_password_strength(new)
    except WeakPassword as exc:
        return JSONResponse({"status": "error", "reason": str(exc)}, status_code=400)
    if verify_password(cred, new):
        # Re-setting the SAME password is not a rotation, and accepting it would
        # clear the clamp while retiring nothing - the one way this whole mechanism
        # could be satisfied without doing its job.
        return JSONResponse(
            {"status": "error", "reason": "the new password must differ"},
            status_code=400,
        )
    await k.store.set_password_credential(realm, user.id, hash_password(new))
    if user.must_change_password:
        await k.store.upsert_user(_replace(user, must_change_password=False))
    # Keys-only ([2026] VJS-COUNTY 7, D8): the fact of the rotation, never a password.
    await _audit(k, realm, user.id, "auth.change_password", {"outcome": "ok"})
    return JSONResponse({"status": "ok"})


def register_password_routes(app, *, principal_dep, get_kernel) -> None:
    K = Depends(get_kernel)
    P = Depends(principal_dep)

    @app.post("/v1/auth/change-password")
    async def change_password(body: dict, request: Request, k=K, p=P) -> JSONResponse:
        """Rotate your own password ([2026] VJS-COUNTY 8, D7).

        The way OUT of the forced-rotation clamp, and the reason that clamp is a
        finished feature rather than a lockout: without this the founding operator
        seeded by `boltrig initiate` could reach only logout and would have to go
        back to a shell to make their own console usable.
        """
        from boltrig.api.auth_routes import _GENERIC_LOGIN_FAILURE
        from boltrig.store.postgres import set_current_tenant

        # A session lives at the identity realm, which differs from the ACTIVE org
        # for a multi-org identity ([2026] VJS-COUNTY 11, D5) - the credential and
        # the flag both travel with the IDENTITY.
        session = getattr(request.state, "boltrig_session", None)
        realm = session.tenant_id if session is not None else p.tenant_id
        set_current_tenant(realm)
        try:
            found, early = await _verified_user(k, p, request, body, realm)
            if early is not None:
                return early
            if found is None:
                return JSONResponse(_GENERIC_LOGIN_FAILURE, status_code=401)
            user, cred = found
            return await _rotate(k, request, body, realm, user, cred)
        finally:
            set_current_tenant(p.tenant_id)
