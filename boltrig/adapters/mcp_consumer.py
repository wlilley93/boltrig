"""Consume an external MCP server as a Boltrig adapter (Round Two, US-MCP-03).

An ``mcp`` adapter connects to an external MCP server, registers its tools as
verbs via ``describe()``, and routes calls back out over MCP. Like any adapter,
its calls run the kernel chokepoint (grants, credentials, audit). A newly
registered MCP server is inert until reviewed and activated (the Round One review
gate, SEC-22): ``execute`` refuses until ``review_and_activate`` is called.

httpx is imported lazily so the module is import-safe offline; a transport can be
injected for tests (and to let Boltrig consume its own MCP face).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from boltrig.adapters.base import AdapterError, Credential, ErrorClass, Result, VerbSpec
from boltrig.models import InvocationContext

# rpc(request: dict) -> response: dict  (a JSON-RPC round-trip to the MCP server)
Rpc = Callable[[dict], Awaitable[dict]]


class McpConsumerAdapter:
    runtime = "mcp"

    def __init__(
        self,
        id: str,
        *,
        url: str | None = None,
        token: str | None = None,
        rpc: Rpc | None = None,
        version: str = "1.0.0",
        source: str = "manual",
    ) -> None:
        self.id = id
        self.version = version
        self.source = source
        self.activated = False  # review gate (SEC-22)
        self._url = url
        self._token = token
        self._rpc = rpc
        self._specs: list[VerbSpec] = []

    async def connect(self) -> list[VerbSpec]:
        """Discover the external server's tools and map them to VerbSpecs."""
        resp = await self._call({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
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
        if not self.activated:  # inert until reviewed (defence in depth, SEC-22)
            return Result.failure(
                AdapterError(ErrorClass.UNAVAILABLE, "mcp server pending review")
            )
        resp = await self._call(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": verb, "arguments": params}}
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

    async def _call(self, request: dict) -> dict:
        if self._rpc is not None:
            return await self._rpc(request)
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                self._url, json=request, headers={"x-boltrig-mcp-token": self._token or ""}
            )
            return r.json()


def build() -> Any:  # loader hook; real config comes from the mcp_servers table
    return McpConsumerAdapter(id="mcp-consumer")
