"""The kernel-tools Codex lane against the real kernel MCP face (fakes only).

No Codex binary needed: this drives the same three points the live cell
traverses and shows they agree on ONE tool set - the run's effective grants:

  1. the admission-side ceiling compiler (tenant ceiling ∩ run grants, the
     resolver's ``_compile_codex_tool_ceiling``) derives exactly the verbs the
     kernel MCP face will advertise over the run-scoped token;
  2. the per-cell model proxy, holding the ceiling as Codex wire names, offers
     exactly the granted tools upstream and strips everything else - built-ins
     AND unlisted boltrig verbs alike - on the request AND the response stream;
  3. a tool call that slips past the ceiling still dies at the kernel
     chokepoint: the run token's grants deny it (SEC-26), so the proxy ceiling
     is defence in depth, never the only wall.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.fleet.infrastructure.codex_kernel_tools_phase import codex_mcp_tool_name
from boltrig.fleet.infrastructure.codex_model_proxy_server import (
    PerCellModelProxyServer,
)
from boltrig.fleet.runtime_resolver import RuntimeResolver
from boltrig.kernel import Kernel
from boltrig.models import GrantSet, TenantPermissions
from boltrig.store import InMemoryStore

T = "acme"
_ALLOWED_WIRE = codex_mcp_tool_name("ticket.read")


async def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store, blocking_verbs=set())
    await kernel.register_adapter(T, build_tickets())
    return kernel


def _req(method: str, params: dict | None = None, rid: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}


async def _proxy(captured: dict[str, Any], allowed: frozenset[str]) -> PerCellModelProxyServer:
    async def _body() -> Any:
        yield b'{"object":"response","output":[]}'

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=_body(),
        )

    async def verify(token: str) -> bool:
        return True

    return PerCellModelProxyServer(
        verify_bearer=verify,
        upstream_base_url="http://gateway/v1",
        upstream_key="KERNEL-ONLY-KEY",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        allowed_tools=allowed,
    )


@pytest.mark.invariant("SEC-184")
async def test_the_ceiling_compiler_and_the_mcp_face_derive_one_tool_set() -> None:
    kernel = await _kernel()
    grants = GrantSet.of(["ticket.read"])
    resolver = RuntimeResolver(kernel, codex_config={"trusted": True})
    ceiling = await resolver._compile_codex_tool_ceiling(T, grants)

    token = kernel.mcp.issue_run_token(T, grants, run_id="r1", actor="codex-run")
    listed = {
        tool["name"]
        for tool in (await kernel.mcp.handle(token, _req("tools/list")))["result"]["tools"]
    }
    # The admission-compiled ceiling IS the set the kernel advertises (FR-MCP-02).
    assert set(ceiling) == listed == {"ticket.read"}


@pytest.mark.invariant("SEC-184")
async def test_the_proxy_offers_exactly_the_granted_wire_names() -> None:
    """The real 0.144.3 payload shape: the boltrig server is ONE namespace entry.

    Verified live against the pinned binary: codex offers
    ``{"type": "namespace", "name": "mcp__boltrig", "tools": [...]}`` with the
    verbs as nested function tools. The proxy must keep the namespace with
    ONLY the granted nested tools, strip every built-in, and drop any other
    namespace outright.
    """
    captured: dict[str, Any] = {}
    proxy = await _proxy(captured, frozenset({_ALLOWED_WIRE}))
    port = await proxy.start()
    try:
        async with httpx.AsyncClient() as caller:
            resp = await caller.post(
                f"http://127.0.0.1:{port}/v1/responses",
                headers={"authorization": "Bearer cell-bearer"},
                content=json.dumps(
                    {
                        "input": "hi",
                        "tools": [
                            {"type": "function", "name": "exec_command"},
                            {"type": "function", "name": _ALLOWED_WIRE},
                            {
                                "type": "namespace",
                                "name": "mcp__boltrig",
                                "description": "Tools in the mcp__boltrig namespace.",
                                "tools": [
                                    {"type": "function", "name": _ALLOWED_WIRE},
                                    {
                                        "type": "function",
                                        "name": codex_mcp_tool_name("jira.create"),
                                    },
                                ],
                            },
                            {
                                "type": "namespace",
                                "name": "mcp__attacker",
                                "tools": [{"type": "function", "name": _ALLOWED_WIRE}],
                            },
                        ],
                    }
                ).encode(),
            )
        assert resp.status_code == 200
        sent = json.loads(captured["body"].decode())
        top = [(tool.get("type"), tool.get("name")) for tool in sent["tools"]]
        assert top == [("function", _ALLOWED_WIRE), ("namespace", "mcp__boltrig")]
        nested = [tool["name"] for tool in sent["tools"][1]["tools"]]
        assert nested == [_ALLOWED_WIRE]  # the granted verb survives, nothing else
    finally:
        await proxy.aclose()


async def test_a_namespace_emptied_by_the_ceiling_is_dropped() -> None:
    captured: dict[str, Any] = {}
    proxy = await _proxy(captured, frozenset({_ALLOWED_WIRE}))
    port = await proxy.start()
    try:
        async with httpx.AsyncClient() as caller:
            resp = await caller.post(
                f"http://127.0.0.1:{port}/v1/responses",
                headers={"authorization": "Bearer cell-bearer"},
                content=json.dumps(
                    {
                        "input": "hi",
                        "tools": [
                            {
                                "type": "namespace",
                                "name": "mcp__boltrig",
                                "tools": [
                                    {
                                        "type": "function",
                                        "name": codex_mcp_tool_name("jira.create"),
                                    }
                                ],
                            }
                        ],
                    }
                ).encode(),
            )
        assert resp.status_code == 200
        sent = json.loads(captured["body"].decode())
        assert "tools" not in sent  # nothing survived, so no tools key at all
    finally:
        await proxy.aclose()


@pytest.mark.invariant("SEC-184")
async def test_the_response_stream_holds_the_same_ceiling() -> None:
    async def verify(token: str) -> bool:
        return True

    def upstream_of(chunk: bytes) -> httpx.AsyncClient:
        async def body() -> Any:
            yield chunk

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=body())

        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    allowed_call = (
        b'data: {"type":"response.output_item.done","item":'
        b'{"type":"function_call","name":"' + _ALLOWED_WIRE.encode() + b'"}}\n\n'
    )
    barred_call = allowed_call.replace(_ALLOWED_WIRE.encode(), b"exec_command")

    proxy = PerCellModelProxyServer(
        verify_bearer=verify,
        upstream_base_url="http://gateway/v1",
        upstream_key="KERNEL-ONLY-KEY",
        client=upstream_of(allowed_call),
        allowed_tools=frozenset({_ALLOWED_WIRE}),
    )
    port = await proxy.start()
    try:
        async with httpx.AsyncClient() as caller:
            resp = await caller.post(
                f"http://127.0.0.1:{port}/v1/responses",
                headers={"authorization": "Bearer cell-bearer"},
                content=b"{}",
            )
            assert _ALLOWED_WIRE.encode() in resp.content  # the allowed call relays
    finally:
        await proxy.aclose()

    proxy = PerCellModelProxyServer(
        verify_bearer=verify,
        upstream_base_url="http://gateway/v1",
        upstream_key="KERNEL-ONLY-KEY",
        client=upstream_of(barred_call),
        allowed_tools=frozenset({_ALLOWED_WIRE}),
    )
    port = await proxy.start()
    try:
        async with httpx.AsyncClient() as caller:
            resp = await caller.post(
                f"http://127.0.0.1:{port}/v1/responses",
                headers={"authorization": "Bearer cell-bearer"},
                content=b"{}",
            )
            assert b"exec_command" not in resp.content  # the barred call truncates
    finally:
        await proxy.aclose()


@pytest.mark.invariant("SEC-26")
@pytest.mark.invariant("SEC-184")
async def test_a_grant_denied_verb_dies_at_the_chokepoint_regardless() -> None:
    """Defence in depth: even a call that reached the kernel is grant-checked."""

    kernel = await _kernel()
    token = kernel.mcp.issue_run_token(T, GrantSet.of(["ticket.read"]), run_id="r1")
    denied = await kernel.mcp.handle(
        token, _req("tools/call", {"name": "ticket.create", "arguments": {"title": "x"}})
    )
    assert denied["result"]["isError"] is True
    assert denied["result"]["_boltrig"]["status"] == "denied"
