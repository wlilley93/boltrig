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
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Protocol

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from boltrig.fleet.domain.model_proxy_grant import StoredModelProxyGrant
from boltrig.fleet.infrastructure.model_proxy_tool_ceiling import (
    MAX_MODEL_CALL_BODY_BYTES,
    CodexResponseStreamProcessor,
    ModelCeilingViolation,
    NativeCollaborationWireGate,
    ReasoningEffortCeilingViolation,
    ToolCeilingViolation,
    enforce_model_ceiling,
    enforce_reasoning_effort_ceiling,
    enforce_tool_ceiling,
)

_LOOPBACK = "127.0.0.1"
_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH"]
_START_TIMEOUT_SECONDS = 5.0

logger = logging.getLogger(__name__)

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
        allowed_model: str,
        allowed_tools: frozenset[str] = frozenset(),
        allowed_reasoning_effort: str | None = None,
        native_collaboration: NativeCollaborationWireGate | None = None,
    ) -> None:
        if type(allowed_tools) is not frozenset:
            raise TypeError("allowed_tools must be an exact frozenset")
        if type(allowed_model) is not str or not allowed_model:
            raise TypeError("allowed_model must be a non-empty string")
        if allowed_reasoning_effort is not None and (
            type(allowed_reasoning_effort) is not str or not allowed_reasoning_effort
        ):
            raise TypeError("allowed_reasoning_effort must be a non-empty string or None")
        if native_collaboration is not None:
            if type(native_collaboration) is not NativeCollaborationWireGate:
                raise TypeError(
                    "native_collaboration must be exact NativeCollaborationWireGate or None"
                )
            if (
                native_collaboration.allowed_model != allowed_model
                or native_collaboration.allowed_reasoning_effort
                != allowed_reasoning_effort
            ):
                raise ValueError(
                    "native collaboration model and effort must match proxy ceilings"
                )
        self._allowed_model = allowed_model
        self._allowed_reasoning_effort = allowed_reasoning_effort
        self._allowed_tools = allowed_tools
        self._native_collaboration = native_collaboration
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
        try:
            # The cell's tool ceiling is enforced HERE, not trusted to the
            # runtime's own config: Codex 0.144.3 cannot suppress its built-in
            # tools, and this proxy is the one point every model call traverses.
            body = enforce_model_ceiling(
                await _capped_body(request), self._allowed_model
            )
            if self._allowed_reasoning_effort is not None:
                body = enforce_reasoning_effort_ceiling(
                    body, self._allowed_reasoning_effort
                )
            body = enforce_tool_ceiling(
                body,
                self._allowed_tools,
                allow_native_collaboration=self._native_collaboration is not None,
            )
        except ModelCeilingViolation:
            return JSONResponse({"error": "model_ceiling"}, status_code=400)
        except ReasoningEffortCeilingViolation:
            return JSONResponse({"error": "reasoning_effort_ceiling"}, status_code=400)
        except ToolCeilingViolation:
            return JSONResponse({"error": "tool_ceiling"}, status_code=400)
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
            # Exclusivity limb (a): the chokepoint is only the only path if the
            # tail cannot leave it. httpx normalizes "/v1/../admin" to "/admin", so
            # without this a cell could reach any gateway endpoint WITH the
            # kernel-only key attached. Check the composed URL, not the raw tail:
            # it is the value that will actually be sent.
            if not str(upstream_request.url).startswith(f"{self._base}/"):
                return JSONResponse({"error": "path_escape"}, status_code=400)
            upstream = await self._client.send(upstream_request, stream=True)
        except httpx.HTTPError:
            # Bounded, body-safe: never leak the key or the upstream error detail.
            return JSONResponse({"error": "upstream_unavailable"}, status_code=502)
        return StreamingResponse(
            self._guarded_stream(upstream),
            status_code=upstream.status_code,
            media_type=_content_type(upstream),
            background=BackgroundTask(upstream.aclose),
        )

    async def _guarded_stream(self, upstream: httpx.Response) -> AsyncIterator[bytes]:
        """Relay the upstream body, holding the ceiling and bridging the namespace.

        Stripping tools from the REQUEST bounds what the model is offered; it does
        not bound what the gateway returns. An unsolicited ``function_call`` in the
        response would still be executed by the App Server, conferring a capability
        by a path that never crossed the request ceiling. The processor also
        reattaches the ``mcp__boltrig`` namespace onto each in-ceiling call (the
        request was flattened, so the gateway returns a bare name Codex cannot
        resolve). On a violation the relay STOPS: status and headers are already
        with the cell, so truncation is the only fail-closed move left, and a
        truncated stream is strictly better than a complete one carrying a barred
        tool call.
        """

        processor = CodexResponseStreamProcessor(
            self._allowed_tools, native_gate=self._native_collaboration
        )
        try:
            async for chunk in upstream.aiter_raw():
                yield processor.feed(chunk)
            yield processor.finish()
        except ToolCeilingViolation as exc:
            # Fail-closed truncation is correct either way; logging just makes an
            # otherwise-silent truncation diagnosable (was this ever hit, and was
            # the ceiling this run held the reason). Never logs stream content,
            # only the static reason.
            logger.warning(
                "model proxy response stream truncated (tool ceiling): %s", exc
            )
            return

    async def _reject_safe(self, token: str) -> bool:
        """Verify the bearer, treating any verifier error as a rejection."""
        try:
            return bool(await self._verify(token))
        except Exception:
            return False


def _content_type(upstream: httpx.Response) -> str:
    raw = upstream.headers.get("content-type")
    return raw.split(";", 1)[0].strip() if raw else "application/json"


async def _capped_body(request: Request) -> bytes:
    """Read the request body under the hard verifiable cap.

    Mirrors the codebase's body-cap idiom (BodySizeLimitMiddleware): a declared
    over-cap Content-Length is refused up front, then the body is STREAMED and
    counted so a chunked over-cap body is rejected as soon as it crosses the cap
    rather than fully buffered - a hostile cell cannot memory-pressure the API
    over loopback. The over-cap refusal is a ToolCeilingViolation: a body we
    cannot afford to buffer is a body whose tool set we cannot verify."""
    declared = request.headers.get("content-length")
    if declared is not None:
        try:  # ToolCeilingViolation subclasses ValueError: keep the raise outside.
            declared_bytes = int(declared)
        except ValueError as error:
            raise ToolCeilingViolation("model-call body has a bad content-length") from error
        if declared_bytes > MAX_MODEL_CALL_BODY_BYTES:
            raise ToolCeilingViolation("model-call body exceeds the verifiable size cap")
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        chunks.append(chunk)
        total += len(chunk)
        if total > MAX_MODEL_CALL_BODY_BYTES:
            raise ToolCeilingViolation("model-call body exceeds the verifiable size cap")
    return b"".join(chunks)


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
