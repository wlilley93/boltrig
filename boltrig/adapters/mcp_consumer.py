"""Consume an external MCP server as a Boltrig adapter (Round Two, US-MCP-03).

An ``mcp`` adapter connects to an external MCP server, registers its tools as
verbs via ``describe()``, and routes calls back out over MCP. Like any adapter,
its calls run the kernel chokepoint (grants, credentials, audit). A newly
registered MCP server is inert until reviewed and activated (the Round One review
gate, SEC-22): ``execute`` refuses until ``review_and_activate`` is called.

The bearer the adapter presents is NEVER held on the instance: it is resolved by
the kernel per call, from the credential seam, and handed to ``execute`` as
``credential`` (SEC-04/05, K-20 - credentials resolve inside the kernel only). A
call with no credential FAILS CLOSED rather than posting an empty bearer.

## Transport interop (Streamable-HTTP and the plain convention)

One HTTP shape serves strict MCP Streamable-HTTP servers AND plain JSON-RPC
doors (the Opbox kernel's ``POST /mcp`` and Boltrig's own MCP face are both the
plain kind):

  * Every POST carries ``Accept: application/json, text/event-stream`` and BOTH
    credential conventions for the same kernel-resolved token:
    ``Authorization: Bearer <token>`` (the spec convention - the only header the
    Opbox door reads) and ``x-boltrig-mcp-token: <token>`` (the Boltrig face's
    convention; it also accepts the bearer form). The token is never logged.
  * The handshake is LAZY: the plain call goes out first. Only a 400/404 - how
    a strict server says "no live session" (no ``initialize`` yet, or an
    expired/unknown ``Mcp-Session-Id``) - triggers the one handshake
    (``initialize`` + a best-effort ``notifications/initialized``) and ONE
    retry of the call. A server that answers plain calls never sees a
    handshake; a server that refuses ``initialize`` is used session-less. A
    session id returned as the ``Mcp-Session-Id`` response header is carried on
    every later POST.
  * A response framed ``text/event-stream`` (SSE) is decoded to the JSON-RPC
    payload it carries; a plain JSON body is read as before.
  * Any other HTTP refusal maps onto the ErrorClass taxonomy with a static
    message - never the response body, which can echo the request (credential
    headers included) back.

httpx is imported lazily so the module is import-safe offline; a transport can be
injected for tests (and to let Boltrig consume its own MCP face).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from boltrig.adapters.base import (
    AdapterError,
    Credential,
    ErrorClass,
    Result,
    VerbSpec,
    bearer_token,
)
from boltrig.models import Consequence, CredentialResolution, InvocationContext

# rpc(request: dict) -> response: dict  (a JSON-RPC round-trip to the MCP server)
Rpc = Callable[[dict], Awaitable[dict]]

# A consumed server may declare a per-tool ``consequence`` hint in the tool
# descriptor. The ceiling is the Consequence enum itself ("high" - the same
# ceiling generated adapters live under, where only mutating verbs reach high):
# an absent or unrecognised hint defaults to "low", so nothing a consumed server
# declares can push a verb above it.
_CONSEQUENCE_HINTS = frozenset({Consequence.LOW.value, Consequence.HIGH.value})

# The protocol revision offered in `initialize`. A server answers with the
# revision IT speaks; the methods used here (initialize, tools/list, tools/call)
# are stable across the dated revisions, so the answer is not negotiated further.
_PROTOCOL_VERSION = "2025-06-18"

_ACCEPT = "application/json, text/event-stream"
_SESSION_HEADER = "mcp-session-id"

# How a strict Streamable-HTTP server says "no live session": no initialize yet
# (400) or an expired/unknown Mcp-Session-Id (404). Either earns ONE handshake +
# retry; any other status is a real refusal, mapped by _status_error.
_SESSION_STATUSES = frozenset({400, 404})


def _status_error(status: int) -> ErrorClass:
    if status in (401, 403):
        return ErrorClass.UNAUTHORISED
    if status == 404:
        return ErrorClass.NOT_FOUND
    if status == 429:
        return ErrorClass.RATE_LIMITED
    if status >= 500:
        return ErrorClass.UNAVAILABLE
    return ErrorClass.INVALID


def _decode_sse(body: str) -> dict:
    """The JSON-RPC response carried by an SSE-framed body: the last ``data``
    event holding a result/error (earlier events may be notifications)."""
    found: dict | None = None
    for event in body.split("\n\n"):
        data = "\n".join(
            line.removeprefix("data:").lstrip()
            for line in event.splitlines()
            if line.startswith("data:")
        )
        if not data:
            continue
        try:
            payload = json.loads(data)
        except ValueError:
            continue
        if isinstance(payload, dict) and ("result" in payload or "error" in payload):
            found = payload
    if found is None:
        raise ValueError("no JSON-RPC response in the mcp event stream")
    return found


def _consequence_hint(tool: dict) -> str:
    hint = str(tool.get("consequence") or "").lower()
    return hint if hint in _CONSEQUENCE_HINTS else Consequence.LOW.value


class _McpFailure(Exception):
    """Internal carrier so a mapped error can bubble to ``execute``.

    ``AdapterError`` is a plain dataclass, so ``raise AdapterError(...)`` is a
    ``TypeError``, not a refusal. Mirrors ``http_base._HttpFailure``, which is the
    established way to carry one out of a helper and convert it at the boundary.
    """

    def __init__(self, error: AdapterError) -> None:
        super().__init__(error.message)
        self.error = error


class McpConsumerAdapter:
    runtime = "mcp"

    def __init__(
        self,
        id: str,
        *,
        url: str | None = None,
        rpc: Rpc | None = None,
        version: str = "1.0.0",
        source: str = "manual",
    ) -> None:
        self.id = id
        self.version = version
        self.source = source
        self.activated = False  # review gate (SEC-22)
        self._url = url
        self._rpc = rpc
        self._specs: list[VerbSpec] = []
        # Server-issued Streamable-HTTP session id (transport state, NOT a
        # credential): captured from an Mcp-Session-Id response header and
        # carried on later POSTs. None = the server speaks the plain convention.
        self._session_id: str | None = None

    async def connect(self, credential: Credential | None = None) -> list[VerbSpec]:
        """Discover the external server's tools and map them to VerbSpecs.

        Discovery runs at ACTIVATION (``control.adapter.activate`` wires it), OUTSIDE
        a dispatch call, so no per-call credential exists yet: the caller passes one
        it resolved through the same kernel seam (``kernel.credentials.resolve_for_adapter``)
        that dispatch uses, after binding the adapter's credential. There is
        deliberately no instance-held token to fall back on, so this path cannot
        become a back door around the per-call credential. Each tool's declared
        ``consequence`` hint propagates to its VerbSpec (see ``_consequence_hint``).
        """
        resp = await self._call(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            bearer_token(credential),
        )
        tools = (resp.get("result") or {}).get("tools", [])
        self._specs = [
            VerbSpec(
                verb_id=t["name"],
                noun_id=t["name"].split(".")[0] if "." in t["name"] else t["name"],
                input_schema=t.get("inputSchema", {}),
                output_schema={"type": "object"},
                description=t.get("description", ""),
                consequence=_consequence_hint(t),
            )
            for t in tools
        ]
        return self._specs

    def describe(self) -> list[VerbSpec]:
        return list(self._specs)

    def review_and_activate(self, reviewer: str) -> "McpConsumerAdapter":
        """Human review gate (SEC-22): activate the consumed server for dispatch."""
        self.activated = True
        return self

    async def execute(
        self, verb: str, params: dict, credential: Credential | None, context: InvocationContext
    ) -> Result:
        try:
            return await self._execute(verb, params, credential)
        except _McpFailure as failure:
            return Result.failure(failure.error)
        except Exception as exc:  # a bad adapter must never crash the kernel (US-ADP-06)
            return Result.failure(
                AdapterError(ErrorClass.INTERNAL, f"adapter error: {type(exc).__name__}")
            )

    async def _execute(
        self, verb: str, params: dict, credential: Credential | None
    ) -> Result:
        if not self.activated:  # inert until reviewed (defence in depth, SEC-22)
            return Result.failure(
                AdapterError(ErrorClass.UNAVAILABLE, "mcp server pending review")
            )
        # The kernel-resolved credential is the ONLY bearer source: no instance
        # token, so rotation and per-run scoping are live and a missing
        # credential fails closed rather than posting an empty bearer.
        if self._rpc is None and bearer_token(credential) is None:
            return Result.failure(
                AdapterError(ErrorClass.UNAUTHORISED, "mcp credential missing")
            )
        resp = await self._call(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": verb, "arguments": params}},
            bearer_token(credential),
        )
        result = resp.get("result") or {}
        boltrig = result.get("_boltrig") or {}
        if result.get("isError"):
            return Result.failure(
                AdapterError(ErrorClass.INVALID, boltrig.get("reason") or "mcp tool error")
            )
        output = boltrig.get("output")
        if output is None:
            # A non-Boltrig MCP server returns the standard content array, not a
            # _boltrig envelope: fall back to mapping its text blocks into output.
            texts = [
                block["text"]
                for block in result.get("content") or []
                if isinstance(block, dict)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            ]
            output = {"text": "\n".join(texts)} if texts else {}
        return Result.success(output)

    async def health(self) -> str:
        return "ok" if self._specs else "unknown"

    async def _call(self, request: dict, bearer: str | None) -> dict:
        if self._rpc is not None:
            # Injected in-process transport (tests, self-consumption): it owns its
            # own auth, so no bearer is derived or sent here.
            return await self._rpc(request)
        if not bearer:
            # Fail closed (defence in depth behind execute's own check, and the
            # guard for connect()): never post an empty bearer, which would be an
            # unauthenticated request.
            raise CredentialResolution(f"no mcp credential resolved for '{self.id}'")
        from boltrig.adapters.egress import EgressBlocked, pinned_async_client

        # SSRF (SEC-61, H2): pin the connection to the vetted IP before
        # posting - this path carries the MCP bearer token, so httpx re-resolving
        # to internal space would both reach internal services AND leak the token.
        # pinned_async_client forces follow_redirects=False.
        try:
            client = pinned_async_client(self._url or "", timeout=30.0)
        except EgressBlocked as exc:
            raise _McpFailure(
                AdapterError(ErrorClass.INVALID, str(exc), retryable=False)
            ) from exc
        async with client:
            return await self._post(client, request, bearer)

    def _headers(self, bearer: str) -> dict:
        # BOTH credential conventions for the same kernel-resolved token: a spec
        # server reads Authorization (it is the only header the Opbox /mcp door
        # reads); the Boltrig face prefers its own header and also accepts the
        # bearer form. The token never enters a log line or an error message.
        headers = {
            "Accept": _ACCEPT,
            "Authorization": f"Bearer {bearer}",
            "x-boltrig-mcp-token": bearer,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    async def _post(self, client: Any, request: dict, bearer: str, *, retried: bool = False) -> dict:
        r = await client.post(self._url, json=request, headers=self._headers(bearer))
        if r.status_code < 400:
            session = r.headers.get(_SESSION_HEADER)
            if session:
                self._session_id = session
            return self._decode(r)
        if r.status_code in _SESSION_STATUSES and not retried:
            # No live session on a strict server: run the ONE handshake, then
            # retry the call once. The refused first attempt never executed
            # (the refusal is the transport's, ahead of dispatch), so the retry
            # is not a replay. Bounded by `retried`; a repeated refusal maps.
            self._session_id = None
            await self._handshake(client, bearer)
            return await self._post(client, request, bearer, retried=True)
        # Static message, never the body: a refusal page can echo the request
        # back, credential headers included.
        raise _McpFailure(
            AdapterError(
                _status_error(r.status_code),
                f"mcp server refused the call (HTTP {r.status_code})",
                retryable=r.status_code == 429 or r.status_code >= 500,
            )
        )

    async def _handshake(self, client: Any, bearer: str) -> None:
        """The MCP handshake, run lazily when a server demands a session.

        A strict Streamable-HTTP server answers ``initialize`` with a result
        and usually an ``Mcp-Session-Id`` to carry from then on; a plain door
        that refuses or cannot answer it is used session-less. Never raises (a
        transport fault re-surfaces on the retried call, typed by ``execute``'s
        catch-all) and never logs - the bearer is on the wire here too.
        """
        try:
            r = await client.post(
                self._url,
                json={
                    "jsonrpc": "2.0", "id": 0, "method": "initialize",
                    "params": {
                        "protocolVersion": _PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "boltrig-mcp-consumer", "version": self.version},
                    },
                },
                headers=self._headers(bearer),
            )
            payload = self._decode(r)
        except Exception:  # a refused/undecodable initialize: plain convention
            return
        if r.status_code >= 400 or not isinstance(payload, dict) or "result" not in payload:
            return
        session = r.headers.get(_SESSION_HEADER)
        if session:
            self._session_id = session
        try:  # best-effort: strict servers 202 it; a plain door may refuse it
            await client.post(
                self._url,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers=self._headers(bearer),
            )
        except Exception:  # the initialized notification is advisory
            pass

    @staticmethod
    def _decode(response: Any) -> dict:
        # A strict Streamable-HTTP server may frame the JSON-RPC payload as an
        # SSE stream instead of returning a plain JSON body.
        if response.headers.get("content-type", "").startswith("text/event-stream"):
            return _decode_sse(response.text)
        return response.json()


def build() -> Any:  # loader hook; real config comes from the mcp_servers table
    return McpConsumerAdapter(id="mcp-consumer")
