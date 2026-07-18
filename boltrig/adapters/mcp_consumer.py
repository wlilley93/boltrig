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

httpx is imported lazily so the module is import-safe offline; a transport can be
injected for tests (and to let Boltrig consume its own MCP face).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from boltrig.adapters.base import AdapterError, Credential, ErrorClass, Result, VerbSpec
from boltrig.models import CredentialResolution, InvocationContext

# rpc(request: dict) -> response: dict  (a JSON-RPC round-trip to the MCP server)
Rpc = Callable[[dict], Awaitable[dict]]


class _McpFailure(Exception):
    """Internal carrier so a mapped error can bubble to ``execute``.

    ``AdapterError`` is a plain dataclass, so ``raise AdapterError(...)`` is a
    ``TypeError``, not a refusal. Mirrors ``http_base._HttpFailure``, which is the
    established way to carry one out of a helper and convert it at the boundary.
    """

    def __init__(self, error: AdapterError) -> None:
        super().__init__(error.message)
        self.error = error


def _bearer(credential: Credential | None) -> str | None:
    """The MCP bearer carried by kernel-resolved credential material, or None.

    Mirrors the runpod adapter's material convention; the material itself is
    never logged or returned (SEC-05), only this derived header value.
    """
    if credential is None:
        return None
    material = credential.material or {}
    for key in ("token", "api_key", "value"):
        value = material.get(key)
        if value:
            return str(value)
    return None


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

    async def connect(self, credential: Credential | None = None) -> list[VerbSpec]:
        """Discover the external server's tools and map them to VerbSpecs.

        Registration-time discovery runs OUTSIDE a dispatch call, so no per-call
        credential exists yet: the caller passes one it resolved through the same
        kernel seam (``kernel.credentials.resolve_for_adapter``) that dispatch
        uses, after binding the adapter's credential. There is deliberately no
        instance-held token to fall back on, so this path cannot become a back
        door around the per-call credential.
        """
        resp = await self._call(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            _bearer(credential),
        )
        tools = (resp.get("result") or {}).get("tools", [])
        self._specs = [
            VerbSpec(
                verb_id=t["name"],
                noun_id=t["name"].split(".")[0] if "." in t["name"] else t["name"],
                input_schema=t.get("inputSchema", {}),
                output_schema={"type": "object"},
                description=t.get("description", ""),
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
        if self._rpc is None and _bearer(credential) is None:
            return Result.failure(
                AdapterError(ErrorClass.UNAUTHORISED, "mcp credential missing")
            )
        resp = await self._call(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": verb, "arguments": params}},
            _bearer(credential),
        )
        result = resp.get("result") or {}
        boltrig = result.get("_boltrig") or {}
        if result.get("isError"):
            return Result.failure(
                AdapterError(ErrorClass.INVALID, boltrig.get("reason") or "mcp tool error")
            )
        return Result.success(boltrig.get("output") or {})

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
            r = await client.post(
                self._url, json=request, headers={"x-boltrig-mcp-token": bearer}
            )
            return r.json()


def build() -> Any:  # loader hook; real config comes from the mcp_servers table
    return McpConsumerAdapter(id="mcp-consumer")
