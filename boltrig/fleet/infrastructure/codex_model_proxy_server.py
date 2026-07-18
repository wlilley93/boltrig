"""Per-cell loopback model proxy: authenticate a Codex cell's model calls by
bearer and forward them to the shared gateway with the kernel-only key.

Ruling [2026] VJS-CC-VJS 1 (Option C): ``SO_PEERCRED`` attests the auth-helper and
gates bearer ISSUANCE (the separate unix-socket channel); THIS TCP proxy
authenticates each ``/v1/responses`` call by the presented bearer, binds
``127.0.0.1`` only (D4), injects the kernel-only upstream key server-side (never
in the cell environment), and forwards to the gateway (bifrost speaks the
Responses API natively, so no wire bridge). Read-only cutover only; the
write/effects phase stays PR8-gated.

Built on Starlette + uvicorn + httpx (the declared server/client stack the kernel
already runs on), not a new dependency. Fail-closed: a missing or unverifiable
bearer is rejected before any upstream call, and an upstream failure is a bounded
502 that never leaks the key or the upstream error body. The bearer verifier is
injected so the concrete grant-store check is wired at the composition root.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from typing import Protocol

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from boltrig.fleet.domain.model_proxy_grant import StoredModelProxyGrant

_LOOPBACK = "127.0.0.1"
_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH"]
_START_TIMEOUT_SECONDS = 5.0

# Verify a presented bearer against the grant store. Returns True only for an
# active, non-expired grant; any error or miss is a reject. Injected so the
# transport never imports or hard-codes a store.
BearerVerifier = Callable[[str], Awaitable[bool]]


class BearerDigestLookup(Protocol):
    """The one grant-store method the proxy verifier needs (structural)."""

    async def find_active_by_bearer_digest(
        self, bearer_digest: str, *, generation: int
    ) -> StoredModelProxyGrant | None: ...


def store_bearer_verifier(
    store: BearerDigestLookup, *, generation: int
) -> BearerVerifier:
    """A :class:`BearerVerifier` backed by the grant store.

    Accepts a presented bearer iff its sha256 digest (the store's issuance digest,
    over the ascii bearer secret) maps to an active, non-expired grant at the given
    rollout generation. A non-ascii or unknown bearer is rejected. This is the
    bearer-authenticated verification the model-call proxy uses under
    [2026] VJS-CC-VJS 1 (issuance was SO_PEERCRED-gated upstream).
    """

    async def verify(bearer: str) -> bool:
        try:
            digest = hashlib.sha256(bearer.encode("ascii")).hexdigest()
        except UnicodeEncodeError:
            return False
        found = await store.find_active_by_bearer_digest(digest, generation=generation)
        return found is not None

    return verify


def _bearer(header: str | None) -> str | None:
    """The token from an ``Authorization: Bearer <token>`` header, or None."""
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token or None


class PerCellModelProxyServer:
    """A loopback HTTP proxy bound to one cell's issued bearer.

    ``start`` binds an ephemeral ``127.0.0.1`` port and returns it (the supervisor
    puts it in the cell's Codex config ``base_url``). Every request is authorised
    by :class:`BearerVerifier` before anything is forwarded upstream.
    """

    def __init__(
        self,
        *,
        verify_bearer: BearerVerifier,
        upstream_base_url: str,
        upstream_key: str,
        client: httpx.AsyncClient,
    ) -> None:
        self._verify = verify_bearer
        self._base = upstream_base_url.rstrip("/")
        self._key = upstream_key
        self._client = client
        self._server: uvicorn.Server | None = None
        self._task: asyncio.Task[None] | None = None
        self._port: int | None = None

    async def start(self) -> int:
        app = Starlette(routes=[Route("/v1/{tail:path}", self._handle, methods=_METHODS)])
        config = uvicorn.Config(
            app,
            host=_LOOPBACK,
            port=0,
            log_level="warning",
            access_log=False,
            lifespan="off",
        )
        self._server = uvicorn.Server(config)
        self._task = asyncio.create_task(self._server.serve())
        await self._await_started()
        self._port = _bound_port(self._server)
        return self._port

    async def aclose(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._task is not None:
            await self._task
            self._task = None
        self._server = None

    @property
    def port(self) -> int:
        if self._port is None:
            raise RuntimeError("model proxy server is not started")
        return self._port

    async def _await_started(self) -> None:
        assert self._server is not None and self._task is not None
        waited = 0.0
        while not self._server.started:
            if self._task.done():  # serve() failed before binding (e.g. bind error)
                self._task.result()  # re-raise the underlying error
                raise RuntimeError("model proxy server exited before start")
            if waited >= _START_TIMEOUT_SECONDS:
                raise TimeoutError("model proxy server did not start in time")
            await asyncio.sleep(0.01)
            waited += 0.01

    async def _handle(self, request: Request) -> Response:
        token = _bearer(request.headers.get("authorization"))
        if token is None or not await self._reject_safe(token):
            # Fail-closed: never reach upstream without an active bearer.
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        tail = request.path_params["tail"]
        body = await request.body()
        headers = {
            "content-type": request.headers.get("content-type", "application/json"),
            "accept": request.headers.get("accept", "application/json"),
            # The kernel-only upstream key is injected here and NEVER seen by the
            # cell; the cell's own bearer is dropped, not forwarded.
            "authorization": f"Bearer {self._key}",
        }
        try:
            upstream_request = self._client.build_request(
                request.method, f"{self._base}/{tail}", content=body, headers=headers
            )
            upstream = await self._client.send(upstream_request, stream=True)
        except httpx.HTTPError:
            # Bounded, body-safe: never leak the key or the upstream error detail.
            return JSONResponse({"error": "upstream_unavailable"}, status_code=502)
        return StreamingResponse(
            upstream.aiter_raw(),
            status_code=upstream.status_code,
            media_type=_content_type(upstream),
            background=BackgroundTask(upstream.aclose),
        )

    async def _reject_safe(self, token: str) -> bool:
        """Verify the bearer, treating any verifier error as a rejection."""
        try:
            return bool(await self._verify(token))
        except Exception:
            return False


def _content_type(upstream: httpx.Response) -> str:
    raw = upstream.headers.get("content-type")
    return raw.split(";", 1)[0].strip() if raw else "application/json"


def _bound_port(server: uvicorn.Server) -> int:
    for started in getattr(server, "servers", None) or ():
        for sock in started.sockets:
            return int(sock.getsockname()[1])
    raise RuntimeError("model proxy server did not bind a socket")


__all__ = [
    "BearerDigestLookup",
    "BearerVerifier",
    "PerCellModelProxyServer",
    "store_bearer_verifier",
]
