"""PiRuntime: pluggable, least-privilege, offline-safe (Epic RUN)."""

import pytest

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.fleet.pi_runtime import PiRuntime
from boltrig.fleet.runtime import build_runtime
from boltrig.kernel import Kernel
from boltrig.models import AgentCapability, GrantSet, InvocationContext, TenantPermissions
from boltrig.store import InMemoryStore

T = "acme"


def _cap() -> AgentCapability:
    return AgentCapability("pi-worker", T, "pi", ["*"], 2, True, "standard", model_endpoint=None)


def _ctx(grants=("*",)):
    return InvocationContext(tenant_id=T, grants=GrantSet.of(list(grants)), actor="pi-worker")


@pytest.mark.invariant("FR-RUN-01")
def test_build_runtime_resolves_pi(monkeypatch):
    # pi is a legacy lane (decision 0012): reachable only behind the explicit
    # rollback opt-in flag.
    monkeypatch.setenv("BOLTRIG_ENABLE_LEGACY_RUNTIMES", "1")
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
    # the sidecar gets exactly: the prompt, the kernel-composed system prompt
    # (floor + tier character, decision Corporate Brain III/V), the scoped MCP
    # connection, the model, and limits - never a tool/verb credential (SEC-27).
    assert set(body) == {"prompt", "system", "mcp", "model", "limits"}
    assert body["mcp"]["token"] == "TOK"
    assert body["model"].get("api_key") in (None, "")  # no model key offline either
    assert "credential" not in repr(body).lower()
    # the system prompt is the governance floor + character - it carries no secret
    assert body["system"] is None or "kernel verbs" in body["system"]


@pytest.mark.invariant("SEC-73")
async def test_pi_run_presents_sidecar_bearer_when_configured(monkeypatch):
    """PiRuntime presents the shared PI_SIDECAR_TOKEN as a bearer so the
    sidecar's fail-closed /run auth accepts it in prod (M2); unset in dev."""
    seen: dict = {}

    class _FakeStream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        async def aiter_lines(self):
            yield '{"type": "final", "output": {}, "summary": "ok"}'

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, method, url, *, json, headers):
            seen["headers"] = headers
            return _FakeStream()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    monkeypatch.setenv("PI_SIDECAR_TOKEN", "shhh")
    rt = PiRuntime(sidecar_url="http://pi", mcp_url="http://mcp", issue_token=lambda *a, **k: "TOK")
    await rt.run("prompt", _ctx(), tools=[])
    assert seen["headers"].get("Authorization") == "Bearer shhh"

    seen.clear()
    monkeypatch.delenv("PI_SIDECAR_TOKEN", raising=False)
    await rt.run("prompt", _ctx(), tools=[])
    assert "Authorization" not in seen["headers"]  # dev: no bearer sent


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
    assert res["result"]["_boltrig"]["status"] == "denied"  # chokepoint denied it
