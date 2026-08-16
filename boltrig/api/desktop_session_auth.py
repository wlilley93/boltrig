"""Session-cookie support for the packaged Tauri account surface."""

from __future__ import annotations

import os

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from boltrig.api.auth_password_routes import register_password_routes
from boltrig.identity import CSRF_COOKIE, SESSION_COOKIE
from boltrig.identity.sessions import SESSION_TTL_HOURS


DESKTOP_WEBVIEW_ORIGINS = frozenset({
    "tauri://localhost",
    "https://tauri.localhost",
})


def _desktop_session_request(request: Request | None) -> bool:
    if request is None:
        return False
    origin = (request.headers.get("origin") or "").rstrip("/")
    configured = {
        item.strip().rstrip("/")
        for item in os.environ.get("BOLTRIG_CORS_ORIGINS", "").split(",")
        if item.strip()
    }
    return origin in DESKTOP_WEBVIEW_ORIGINS and origin in configured


def set_session_cookies(
    response: JSONResponse,
    secret: str,
    csrf: str,
    *,
    secure: bool,
    request: Request | None = None,
) -> None:
    """Set Strict web cookies or explicitly allowlisted Tauri cookies."""
    same_site = "none" if secure and _desktop_session_request(request) else "strict"
    max_age = SESSION_TTL_HOURS * 3600
    response.set_cookie(
        SESSION_COOKIE,
        secret,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite=same_site,
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=max_age,
        httponly=False,
        secure=secure,
        samesite=same_site,
        path="/",
    )


def register_session_csrf_route(app, principal_dep) -> None:
    """Expose only the authenticated session's own CSRF token."""
    principal = Depends(principal_dep)

    @app.get("/v1/auth/csrf")
    async def session_csrf(request: Request, _principal=principal) -> JSONResponse:
        session = getattr(request.state, "boltrig_session", None)
        if session is None or not session.csrf_token:
            return JSONResponse(
                {"status": "error", "reason": "no session"},
                status_code=401,
            )
        return JSONResponse({"status": "ok", "csrf_token": session.csrf_token})


def register_auth_support_routes(app, principal_dep, get_kernel) -> None:
    """Register the extracted password and desktop-session support surfaces."""
    register_password_routes(app, principal_dep=principal_dep, get_kernel=get_kernel)
    register_session_csrf_route(app, principal_dep)
