"""The kernel MCP server face (Epic MCP): granted-only tools + chokepoint parity.

Every tools/call runs the unchanged dispatch order, so grants, the HITL gate, and
audit apply identically to a direct invoke (SEC-26). A run-scoped token exposes
only that run's tools (SEC-23, FR-MCP-02).
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import GrantSet, TenantPermissions
from boltrig.store import InMemoryStore

T = "acme"


async def _kernel(blocking=None) -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store, blocking_verbs=blocking or set())
    await k.register_adapter(T, build_tickets())
    return k


def _req(method, params=None, rid=1):
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}


@pytest.mark.security
@pytest.mark.invariant("FR-MCP-01")
async def test_tools_list_is_granted_only_with_schemas():
    k = await _kernel()
    tok = k.mcp.issue_run_token(T, GrantSet.of(["ticket.read"]))
    res = await k.mcp.handle(tok, _req("tools/list"))
    tools = {t["name"]: t for t in res["result"]["tools"]}
    assert set(tools) == {"ticket.read"}  # ticket.create is out of this run's grants
    assert "id" in tools["ticket.read"]["inputSchema"]["properties"]  # schema advertised


@pytest.mark.security
@pytest.mark.invariant("SEC-26")
async def test_tools_call_runs_chokepoint_and_audits():
    k = await _kernel()
    tok = k.mcp.issue_run_token(T, GrantSet.of(["ticket.create"]), run_id="r1", actor="pi-run")
    res = await k.mcp.handle(
        tok, _req("tools/call", {"name": "ticket.create", "arguments": {"title": "x"}})
    )
    assert res["result"]["isError"] is False
    assert res["result"]["_boltrig"]["output"]["status"] == "open"
    events = await k.store.audit_query(T)
    assert events[-1].verb == "ticket.create" and events[-1].actor == "pi-run"


@pytest.mark.security
@pytest.mark.invariant("FR-MCP-02")
@pytest.mark.invariant("SEC-23")
async def test_out_of_scope_verb_not_listed_and_denied():
    k = await _kernel()
    tok = k.mcp.issue_run_token(T, GrantSet.of(["ticket.read"]))  # cannot create
    listed = {t["name"] for t in (await k.mcp.handle(tok, _req("tools/list")))["result"]["tools"]}
    assert "ticket.create" not in listed
    # defence in depth: calling it anyway is denied at the chokepoint
    call = await k.mcp.handle(
        tok, _req("tools/call", {"name": "ticket.create", "arguments": {"title": "x"}})
    )
    assert call["result"]["isError"] is True
    assert call["result"]["_boltrig"]["status"] == "denied"


@pytest.mark.security
@pytest.mark.invariant("SEC-26")
async def test_mcp_hitl_gate_parity():
    k = await _kernel(blocking={"ticket.create"})
    tok = k.mcp.issue_run_token(T, GrantSet.of(["ticket.create"]))
    res = await k.mcp.handle(
        tok, _req("tools/call", {"name": "ticket.create", "arguments": {"title": "x"}})
    )
    assert res["result"]["_boltrig"]["status"] == "pending_human"
    assert res["result"]["_boltrig"]["hitl_request_id"]


@pytest.mark.security
async def test_invalid_token_rejected():
    k = await _kernel()
    res = await k.mcp.handle("not-a-token", _req("tools/list"))
    assert "error" in res


@pytest.mark.security
def test_mcp_http_route():
    k = asyncio.run(_kernel())
    tok = k.mcp.issue_run_token(T, GrantSet.of(["ticket.read"]))
    client = TestClient(create_app(k))
    r = client.post("/v1/mcp", json=_req("tools/list"), headers={"x-boltrig-mcp-token": tok})
    assert r.status_code == 200
    assert any(t["name"] == "ticket.read" for t in r.json()["result"]["tools"])
