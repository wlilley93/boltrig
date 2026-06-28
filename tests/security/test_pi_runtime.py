"""PiRuntime: pluggable, least-privilege, offline-safe (Epic RUN)."""

import pytest

from nankle.adapters.builtin.memory_tickets import build as build_tickets
from nankle.fleet.pi_runtime import PiRuntime
from nankle.fleet.runtime import build_runtime
from nankle.kernel import Kernel
from nankle.models import AgentCapability, GrantSet, InvocationContext, TenantPermissions
from nankle.store import InMemoryStore

T = "acme"


def _cap() -> AgentCapability:
    return AgentCapability("pi-worker", T, "pi", ["*"], 2, True, "standard", model_endpoint=None)


def _ctx(grants=("*",)):
    return InvocationContext(tenant_id=T, grants=GrantSet.of(list(grants)), actor="pi-worker")


@pytest.mark.invariant("FR-RUN-01")
def test_build_runtime_resolves_pi():
    rt = build_runtime(_cap())
    assert isinstance(rt, PiRuntime) and rt.runtime == "pi"


@pytest.mark.invariant("FR-RUN-05")
async def test_pi_degrades_without_sidecar():
    rt = PiRuntime(sidecar_url=None, issue_token=lambda *a, **k: "t")
    res = await rt.run("hello", _ctx(), tools=[])
    assert res.ok and res.output.get("_degraded", {}).get("runtime") == "pi"


@pytest.mark.invariant("FR-RUN-02")
@pytest.mark.invariant("SEC-27")
def test_sidecar_request_carries_no_tool_credentials():
    rt = PiRuntime(sidecar_url="http://pi", mcp_url="http://mcp", issue_token=lambda *a, **k: "TOK")
    body = rt.build_request("prompt", _ctx(), "TOK")
    # the sidecar gets exactly: the prompt, the scoped MCP connection, the model,
    # and limits - never a tool/verb credential (SEC-27); its only tools are MCP.
    assert set(body) == {"prompt", "mcp", "model", "limits"}
    assert body["mcp"]["token"] == "TOK"
    assert body["model"].get("api_key") in (None, "")  # no model key offline either
    assert "credential" not in repr(body).lower()


@pytest.mark.invariant("FR-RUN-03")
async def test_pi_run_tool_call_passes_chokepoint():
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    await k.register_adapter(T, build_tickets())
    # a Pi run scoped to ticket.read (the token PiRuntime would issue) cannot create
    token = k.mcp.issue_run_token(T, GrantSet.of(["ticket.read"]), run_id="r1", actor="pi-worker")
    res = await k.mcp.handle(
        token,
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "ticket.create", "arguments": {"title": "x"}}},
    )
    assert res["result"]["_nankle"]["status"] == "denied"  # chokepoint denied it
