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

import json
import os

from fastapi import FastAPI, Request
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


def client_ip(request: Request) -> str | None:
    """The caller's client IP for audit provenance and per-IP rate limits.

    ``CF-Connecting-IP`` is honored ONLY when the deployment opts in with
    ``BOLTRIG_TRUST_CF_CONNECTING_IP`` (set it only behind the Cloudflare tunnel,
    where CF sets the header and strips any client-supplied copy); otherwise the
    header is client-spoofable and the TCP peer is used. X-Forwarded-For is
    deliberately NEVER trusted (spoofable unless behind a known trusted proxy).
    """
    # Lazy: boltrig.config pulls in identity, which imports kernel.app - a
    # module-level import here would close a cycle.
    from boltrig.config.environment import is_truthy

    if is_truthy(os.environ.get("BOLTRIG_TRUST_CF_CONNECTING_IP")):
        cf = request.headers.get("cf-connecting-ip")
        if cf:
            return cf
    return request.client.host if request.client else None

# Per-path body-cap overrides: the Knowledge upload route stages immutable
# originals up to knowledge.models.MAX_UPLOAD_BYTES (25 MiB) over HTTP (KNO-01),
# so the global 1 MiB cap would reject every upload above 1 MiB first. The route
# still enforces its own exact cap; every other path keeps the global limit.
_PATH_BODY_CAPS = (("/v1/knowledge/uploads/", 25 * 1024 * 1024),)


def _csv(value: str | None) -> list[str]:
    return [p.strip() for p in (value or "").split(",") if p.strip()]


def _production_signal(env: dict) -> bool:
    """Return True if a production signal is present in the env (IAM-09)."""
    # Lazy: boltrig.config pulls in identity, which imports kernel.app - a
    # module-level import here would close a cycle (see client_ip).
    from boltrig.config.environment import is_truthy

    if is_truthy(env.get("BOLTRIG_PRODUCTION")):
        return True
    for key in ("ENV", "BOLTRIG_ENV", "APP_ENV"):
        if (env.get(key) or "").strip().lower() in {"prod", "production", "staging"}:
            return True
    return False


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Stamp the security headers on every response (WEB-02/03)."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for k, v in _SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response


class BodySizeLimitMiddleware:
    """Reject a request whose declared/streamed body exceeds the cap (RES-01)."""

    def __init__(self, app, *, max_bytes: int) -> None:
        self.app = app
        self._max = max_bytes

    async def _error(self, send, status: int, message: str) -> None:
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [[b"content-type", b"application/json"]],
        })
        await send({
            "type": "http.response.body",
            "body": json.dumps({"error": message}).encode(),
        })

    _BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})

    def _max_for(self, path: str) -> int:
        for prefix, cap in _PATH_BODY_CAPS:
            if path.startswith(prefix):
                return cap
        return self._max

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        max_bytes = self._max_for(scope.get("path") or "")
        headers = dict(scope.get("headers", []))
        cl = headers.get(b"content-length")
        if cl is not None:
            try:
                if int(cl.decode()) > max_bytes:
                    await self._error(send, 413, "payload_too_large")
                    return
            except ValueError:
                await self._error(send, 400, "bad_content_length")
                return
            await self.app(scope, receive, send)
            return

        # Methods that do not carry a body can skip the buffering path. This avoids
        # blocking on receive() for SSE GET requests and similar streams.
        if scope.get("method") not in self._BODY_METHODS:
            await self.app(scope, receive, send)
            return

        # Chunked or otherwise length-uncapped bodies: buffer and count bytes, then
        # replay so the app sees a normal request when under the cap.
        chunks: list[bytes] = []
        total = 0
        while True:
            msg = await receive()
            if msg["type"] == "http.request":
                chunk = msg.get("body", b"")
                chunks.append(chunk)
                total += len(chunk)
                if total > max_bytes:
                    await self._error(send, 413, "payload_too_large")
                    return
                if not msg.get("more_body", False):
                    break
            elif msg["type"] == "http.disconnect":
                break

        idx = 0

        async def replay_receive():
            nonlocal idx
            if idx < len(chunks):
                body = chunks[idx]
                idx += 1
                return {"type": "http.request", "body": body, "more_body": idx < len(chunks)}
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay_receive, send)


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
    if hosts == ["*"] and _production_signal(e):
        raise RuntimeError(
            "FATAL: BOLTRIG_ALLOWED_HOSTS is '*' in production. "
            "Set an explicit host allowlist (WEB-06)."
        )
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
