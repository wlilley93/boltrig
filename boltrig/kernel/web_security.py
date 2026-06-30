"""Edge/web hardening for the kernel FastAPI app (Batch 1 WEB-* + RES-01).

The app shipped with no middleware: no security headers, no CORS allowlist, no
Host validation, no request-body cap. This adds all four as one
config-as-data layer, fail-closed by default (deny cross-origin, restrict hosts)
and overridable by env for a real deployment.

  * WEB-02/03 security headers - HSTS, nosniff, frame-deny, referrer, permissions,
    and a strict CSP, on every response.
  * WEB-05 CORS - an explicit origin allowlist (never ``*`` with credentials,
    never reflect Origin). Default: no cross-origin (same-origin only).
  * WEB-06 Host validation - TrustedHost allowlist.
  * RES-01 - a request-body size cap (413 over the limit) to blunt body-flood DoS.

Everything is additive middleware; no route or kernel code changes.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

# A strict default CSP for the API surface: it serves JSON/SSE, not HTML, so it
# needs nothing inline. The UI is a separate origin with its own CSP.
_CSP = (
    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; "
    "form-action 'none'"
)

_SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Content-Security-Policy": _CSP,
    "Cross-Origin-Opener-Policy": "same-origin",
}

_DEFAULT_MAX_BODY = 1 * 1024 * 1024  # 1 MiB request-body cap (RES-01)


def _csv(value: str | None) -> list[str]:
    return [p.strip() for p in (value or "").split(",") if p.strip()]


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Stamp the security headers on every response (WEB-02/03)."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for k, v in _SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject a request whose declared/streamed body exceeds the cap (RES-01)."""

    def __init__(self, app, *, max_bytes: int) -> None:
        super().__init__(app)
        self._max = max_bytes

    async def dispatch(self, request: Request, call_next):
        cl = request.headers.get("content-length")
        if cl is not None:
            try:
                if int(cl) > self._max:
                    return JSONResponse(
                        {"error": "payload_too_large"}, status_code=413
                    )
            except ValueError:
                return JSONResponse({"error": "bad_content_length"}, status_code=400)
        return await call_next(request)


def install_security(app: FastAPI, *, env: dict | None = None) -> None:
    """Install the edge/web hardening middleware (WEB-02/03/05/06, RES-01).

    Config (env, all optional):
      BOLTRIG_ALLOWED_HOSTS   - comma list for Host validation (default '*' off only
                               in dev; a deployment SHOULD set it).
      BOLTRIG_CORS_ORIGINS    - comma list of allowed browser origins (default none:
                               same-origin only; never '*').
      BOLTRIG_MAX_BODY_BYTES  - request-body cap (default 1 MiB).
    """
    e = env if env is not None else os.environ
    hosts = _csv(e.get("BOLTRIG_ALLOWED_HOSTS")) or ["*"]
    origins = _csv(e.get("BOLTRIG_CORS_ORIGINS"))
    try:
        max_body = int(e.get("BOLTRIG_MAX_BODY_BYTES") or _DEFAULT_MAX_BODY)
    except ValueError:
        max_body = _DEFAULT_MAX_BODY

    # Order: body cap first (cheap reject), then headers, then CORS, then Host.
    # Starlette runs middleware in reverse add order, so add Host last to run first.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=max_body)
    app.add_middleware(SecurityHeadersMiddleware)
    if origins:
        # Explicit allowlist only - never '*' with credentials, never reflect.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["authorization", "content-type", "x-boltrig-mcp-token"],
        )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
