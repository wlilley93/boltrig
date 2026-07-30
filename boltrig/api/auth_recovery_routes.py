"""Public password recovery through the fail-closed ``deliver_password_reset`` seam.

SEC-AUTH-RECOVERY-01: request responses do not enumerate accounts; the only
persisted bearer material is a SHA-256 digest; reset tokens are expiring and
single-use; successful redemption atomically rotates the credential, clears the
forced-rotation flag, revokes browser sessions, and drops pending 2FA challenges.
"""

from __future__ import annotations

from fastapi import BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse

from boltrig.identity import (
    CSRF_COOKIE,
    RESET_TOKEN_TTL,
    SESSION_COOKIE,
    PasswordResetNotice,
    deliver_password_reset,
    generate_password_reset_token,
    hash_password,
    hash_password_reset_token,
    validate_password_strength,
)
from boltrig.identity.passwords import WeakPassword
from boltrig.kernel.web_security import client_ip as _client_ip
from boltrig.models import RateLimited, SecurityEventType, utcnow
from boltrig.models.access import PasswordResetToken
from boltrig.models.registry import RateLimit


_REQUEST_RL_IDENTITY = RateLimit(per="hour", max=3, scope="verb")
_REQUEST_RL_IP = RateLimit(per="hour", max=10, scope="verb")
_CONFIRM_RL_TOKEN = RateLimit(per="minute", max=5, scope="verb")
_CONFIRM_RL_IP = RateLimit(per="minute", max=30, scope="verb")

_GENERIC_REQUEST = {
    "status": "ok",
    "message": "If the account can be recovered, reset instructions have been sent.",
}
_GENERIC_INVALID_TOKEN = {
    "status": "error",
    "reason": "invalid or expired reset token",
}
_TOO_MANY = {"status": "error", "reason": "too many attempts"}


def _notifier(request: Request):
    platform = getattr(request.app.state, "platform", None)
    return platform.get("password_reset_notifier") if isinstance(platform, dict) else None


async def _issue_and_notify(k, tenant: str, email: str, notifier) -> None:
    """Use ``replace_password_reset_token`` to issue only for an active
    credential-backed identity, then call ``deliver_password_reset`` once.

    This runs after the generic response has been selected. A notifier failure
    deletes this exact digest; it cannot erase a newer concurrently issued token.
    Plaintext bearer material never enters audit, logs, exceptions, or responses.
    """

    from boltrig.api.auth_routes import _audit
    from boltrig.store.postgres import set_current_tenant

    set_current_tenant(tenant)
    secret = generate_password_reset_token()
    token_hash = hash_password_reset_token(secret)
    expires_at = utcnow() + RESET_TOKEN_TTL
    created = await k.store.replace_password_reset_token(
        PasswordResetToken(
            tenant_id=tenant,
            user_id=email,
            token_hash=token_hash,
            expires_at=expires_at,
        )
    )
    if not created:
        await _audit(
            k,
            tenant,
            email or "unknown",
            "auth.password_reset.delivery",
            {"outcome": "not_sent"},
            status="denied",
        )
        return

    delivered = False
    try:
        delivered = await deliver_password_reset(
            notifier,
            PasswordResetNotice(email=email, token=secret, expires_at=expires_at),
        )
    except Exception:
        # The delivery adapter is outside the trust boundary. Its exception text
        # may contain provider payloads, so it is intentionally neither logged nor
        # copied into audit.
        delivered = False
    if not delivered:
        await k.store.invalidate_password_reset_token(tenant, token_hash)
    await _audit(
        k,
        tenant,
        email,
        "auth.password_reset.delivery",
        {
            "outcome": (
                "accepted_by_notifier" if delivered else "not_sent"
            )
        },
        status="ok" if delivered else "denied",
    )


async def _request_password_reset(body, request, background_tasks, k) -> JSONResponse:
    """Accept a recovery request without revealing whether the account exists."""

    from boltrig.api.auth_routes import _audit, _console_tenant, _norm_email
    from boltrig.store.postgres import set_current_tenant

    tenant = _console_tenant()
    set_current_tenant(tenant)
    email = _norm_email(body.get("email"))
    client_ip = _client_ip(request) or "unknown"
    user_agent = request.headers.get("user-agent") or None
    try:
        # Existing, absent, and deactivated identities consume the same buckets
        # before any identity lookup.
        await k.rate_limiter.enforce(
            tenant, f"auth.password_reset.request.ip:{client_ip}", _REQUEST_RL_IP
        )
        await k.rate_limiter.enforce(
            tenant, f"auth.password_reset.request.id:{email}", _REQUEST_RL_IDENTITY
        )
    except RateLimited:
        await k.security.record(
            tenant,
            SecurityEventType.RATE_LIMIT_TRIP,
            "password_reset_request_rate_limited",
            actor=email or "unknown",
            actor_tier="human",
            ip_address=client_ip,
            user_agent=user_agent,
            resource="auth.password_reset.request",
        )
        return JSONResponse(_TOO_MANY, status_code=429)

    await _audit(
        k,
        tenant,
        email or "unknown",
        "auth.password_reset.request",
        {"outcome": "accepted"},
    )
    notifier = _notifier(request)
    if notifier is None:
        # No console/log fallback: absent explicit delivery means no minted bearer.
        await _audit(
            k,
            tenant,
            email or "unknown",
            "auth.password_reset.delivery",
            {"outcome": "unavailable"},
            status="denied",
        )
    else:
        background_tasks.add_task(_issue_and_notify, k, tenant, email, notifier)
    return JSONResponse(_GENERIC_REQUEST, status_code=202)


async def _confirm_password_reset(body, request, k) -> JSONResponse:
    """Redeem an expiring token once; do not issue a replacement session."""

    from boltrig.api.auth_routes import _audit, _console_tenant
    from boltrig.store.postgres import set_current_tenant

    tenant = _console_tenant()
    set_current_tenant(tenant)
    token = body.get("token")
    token = token if isinstance(token, str) else ""
    password = body.get("new_password")
    password = password if isinstance(password, str) else ""
    client_ip = _client_ip(request) or "unknown"
    user_agent = request.headers.get("user-agent") or None
    token_hash = hash_password_reset_token(token)
    try:
        await k.rate_limiter.enforce(
            tenant, f"auth.password_reset.confirm.ip:{client_ip}", _CONFIRM_RL_IP
        )
        await k.rate_limiter.enforce(
            tenant, f"auth.password_reset.confirm.token:{token_hash}", _CONFIRM_RL_TOKEN
        )
    except RateLimited:
        await k.security.record(
            tenant,
            SecurityEventType.RATE_LIMIT_TRIP,
            "password_reset_confirm_rate_limited",
            actor="unknown",
            actor_tier="human",
            ip_address=client_ip,
            user_agent=user_agent,
            resource="auth.password_reset.confirm",
        )
        return JSONResponse(_TOO_MANY, status_code=429)
    try:
        validate_password_strength(password)
    except WeakPassword as exc:
        return JSONResponse({"status": "error", "reason": str(exc)}, status_code=400)

    result = await k.store.reset_password_with_token(
        tenant, token_hash, hash_password(password), utcnow()
    )
    if result is None:
        await _reject_invalid_token(k, tenant, client_ip, user_agent)
        return JSONResponse(_GENERIC_INVALID_TOKEN, status_code=400)
    await _audit(
        k,
        tenant,
        result.user_id,
        "auth.password_reset.confirm",
        {"outcome": "ok", "revoked_sessions": result.revoked_sessions},
    )
    response = JSONResponse({"status": "ok"})
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return response


async def _reject_invalid_token(k, tenant, client_ip, user_agent) -> None:
    from boltrig.api.auth_routes import _audit

    await _audit(
        k,
        tenant,
        "unknown",
        "auth.password_reset.confirm",
        {"outcome": "rejected"},
        status="denied",
    )
    await k.security.record(
        tenant,
        SecurityEventType.LOGIN_FAILURE,
        "invalid_password_reset_token",
        actor="unknown",
        actor_tier="human",
        ip_address=client_ip,
        user_agent=user_agent,
        resource="auth.password_reset.confirm",
    )


def register_recovery_routes(app, *, get_kernel) -> None:
    K = Depends(get_kernel)

    @app.post("/v1/auth/password-reset/request")
    async def request_password_reset(
        body: dict, request: Request, background_tasks: BackgroundTasks, k=K
    ):
        return await _request_password_reset(body, request, background_tasks, k)

    @app.post("/v1/auth/password-reset/confirm")
    async def confirm_password_reset(body: dict, request: Request, k=K):
        return await _confirm_password_reset(body, request, k)
