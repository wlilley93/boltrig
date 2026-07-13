"""Ephemeral spawn: cheapest-capable selection, depth + context guards (Epic FLT)."""

import stat

import pytest

from boltrig.fleet import build_spawner
from boltrig.fleet.result import AgentResult
from boltrig.kernel import Kernel
from boltrig.models import (
    AgentCapability,
    ContextRequirementsUnmet,
    DepthExceeded,
    GrantSet,
    InvocationContext,
    ModelEndpoint,
    Skill,
    TenantPermissions,
)
from boltrig.store import InMemoryStore

T = "acme"


async def _kernel_with_caps() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    # two capable runtimes; the cheap one must win
    await store.upsert_capability(
        AgentCapability("script-worker", T, "python-script", ["*"], 2, True, "cheap")
    )
    await store.upsert_capability(
        AgentCapability("claude-api-worker", T, "claude-api", ["*"], 2, True, "expensive")
    )
    await store.upsert_capability(
        AgentCapability("preferred-script", T, "python-script", ["*"], 2, True, "expensive")
    )
    await store.upsert_skill(
        Skill(
            id="analysis/decompose",
            tenant_id=T,
            version="1.0.0",
            prompt_fragment="Decompose the task.",
            tool_grants=["ticket.read"],
            context_requirements={
                "type": "object",
                "required": ["epic_id"],
                "properties": {"epic_id": {"type": "string"}},
            },
        )
    )
    return Kernel(store)


def _ctx(depth: int = 0, *, epic_id: str | None = "ENG-441") -> InvocationContext:
    extra = {"epic_id": epic_id} if epic_id is not None else {}
    return InvocationContext(
        tenant_id=T, grants=GrantSet.of(["*"]), actor="head", depth=depth, extra=extra
    )


@pytest.mark.invariant("US-FLT-04")
async def test_cheapest_capable_runtime_chosen():
    kernel = await _kernel_with_caps()
    spawner = build_spawner(kernel)
    res = await spawner.spawn(
        T, "decompose epic", ["analysis/decompose"], {}, _ctx(),
    )
    assert res["agent_type"] == "script-worker"  # cheap beats expensive
    assert "run_id" in res


@pytest.mark.invariant("FR-RUN-15")
async def test_opencode_spawn_preserves_workspace_for_scoped_mcp(monkeypatch, tmp_path):
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    await store.upsert_model_endpoint(
        ModelEndpoint(
            id="opencode-ornith",
            tenant_id=T,
            kind="opencode",
            model="ornith/test",
            base_url=None,
        )
    )
    await store.upsert_capability(
        AgentCapability(
            "opencode-worker",
            T,
            "opencode",
            ["*"],
            2,
            True,
            "cheap",
            model_endpoint="opencode-ornith",
        )
    )
    await store.upsert_skill(
        Skill(
            id="analysis/decompose",
            tenant_id=T,
            version="1.0.0",
            prompt_fragment="Decompose the task.",
            tool_grants=["ticket.read"],
        )
    )
    script = tmp_path / "fake-opencode"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "print(json.dumps({'type': 'message', 'text': 'ok'}))\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("BOLTRIG_OPENCODE_BIN", str(script))
    monkeypatch.setenv("BOLTRIG_OPENCODE_MCP_URL", "http://kernel.example/v1/mcp")

    kernel = Kernel(store)
    issued: list[dict] = []

    def issue_token(*args, **kwargs):
        issued.append({"args": args, "kwargs": kwargs})
        return "RUN_TOKEN"

    monkeypatch.setattr(kernel.mcp, "issue_run_token", issue_token)
    spawner = build_spawner(kernel)
    parent = InvocationContext(
        tenant_id=T,
        run_id="parent-run",
        workspace_id="ws-1",
        ip_address="203.0.113.10",
        user_agent="test-agent",
        grants=GrantSet.of(["*"]),
        actor="head",
        on_behalf_of="alice",
        extra={"principal_role": "org-admin"},
    )
    res = await spawner.spawn(T, "decompose epic", ["analysis/decompose"], {}, parent)

    assert res["agent_type"] == "opencode-worker"
    assert issued
    assert issued[0]["kwargs"] == {
        "run_id": res["run_id"],
        "actor": "opencode-worker",
        "skills": ("analysis/decompose",),
        "workspace_id": "ws-1",
        "on_behalf_of": "alice",
        "extra": {"principal_role": "org-admin"},
    }
    assert issued[0]["args"][0] == T


async def test_rivet_spawn_preserves_workspace_for_scoped_mcp(monkeypatch):
    from boltrig.fleet.rivet_runtime import RivetAgentOSRuntime

    monkeypatch.setenv("RIVET_AGENTOS_URL", "http://rivet-agentos:2468")
    monkeypatch.setenv("BOLTRIG_RIVET_MCP_URL", "http://kernel.example/v1/mcp")
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    await store.upsert_model_endpoint(
        ModelEndpoint(
            id="standard",
            tenant_id=T,
            kind="openai",
            model="glm-5.2",
            base_url="https://models.example/v1",
        )
    )
    await store.upsert_capability(
        AgentCapability(
            "rivet-worker", T, "rivet_agentos", ["*"], 2, True, "cheap",
            model_endpoint="standard",
        )
    )
    await store.upsert_skill(
        Skill(
            id="analysis/decompose",
            tenant_id=T,
            version="1.0.0",
            prompt_fragment="Decompose the task.",
            tool_grants=["ticket.read"],
        )
    )
    seen = {}

    async def fake_post(self, url, payload, headers):
        seen.update({"url": url, "payload": payload, "headers": headers})
        return 200, {"summary": "done", "output": {"ok": True}, "tokens_used": 5}

    monkeypatch.setattr(RivetAgentOSRuntime, "_post", fake_post)
    kernel = Kernel(store)
    issued: list[dict] = []

    def issue_token(*args, **kwargs):
        issued.append({"args": args, "kwargs": kwargs})
        return "RIVET_RUN_TOKEN"

    revoked: list[str] = []
    monkeypatch.setattr(kernel.mcp, "issue_run_token", issue_token)
    monkeypatch.setattr(kernel.mcp, "revoke", revoked.append)
    spawner = build_spawner(kernel)
    parent = InvocationContext(
        tenant_id=T,
        run_id="parent-run",
        workspace_id="ws-1",
        grants=GrantSet.of(["*"]),
        actor="head",
    )

    res = await spawner.spawn(
        T, "decompose epic", ["analysis/decompose"], {"capability": "rivet-worker"}, parent
    )

    assert res["agent_type"] == "rivet-worker"
    assert res["degraded"] is False
    assert seen["url"] == "http://rivet-agentos:2468/runs"
    assert seen["payload"]["mcp"] == {
        "url": "http://kernel.example/v1/mcp",
        "token": "RIVET_RUN_TOKEN",
    }
    assert seen["payload"]["context"]["workspace_id"] == "ws-1"
    assert seen["payload"]["context"]["skills"] == ["analysis/decompose"]
    assert issued[0]["kwargs"]["workspace_id"] == "ws-1"
    assert revoked == ["RIVET_RUN_TOKEN"]


@pytest.mark.invariant("US-FLT-04")
async def test_preferred_capability_chosen_when_capable():
    kernel = await _kernel_with_caps()
    spawner = build_spawner(kernel)
    res = await spawner.spawn(
        T, "decompose epic", ["analysis/decompose"],
        {"capability": "preferred-script"}, _ctx(),
    )
    assert res["agent_type"] == "preferred-script"


async def test_context_requirements_validated():
    kernel = await _kernel_with_caps()
    spawner = build_spawner(kernel)
    # the spawn context is missing the required epic_id
    with pytest.raises(ContextRequirementsUnmet):
        await spawner.spawn(T, "x", ["analysis/decompose"], {}, _ctx(epic_id=None))


@pytest.mark.invariant("FR-EXE-03")
async def test_depth_limit_enforced():
    kernel = await _kernel_with_caps()
    spawner = build_spawner(kernel)
    # depth already at the capability max_depth (2) -> spawning a child exceeds it
    with pytest.raises(DepthExceeded):
        await spawner.spawn(
            T, "x", ["analysis/decompose"], {}, _ctx(depth=2),
        )


@pytest.mark.invariant("FR-OBS-11")
async def test_spawn_audit_records_latency_for_model_telemetry(monkeypatch):
    kernel = await _kernel_with_caps()
    spawner = build_spawner(kernel)

    class _Runtime:
        runtime = "fake"
        cost_tier = "cheap"
        model_route = {
            "profile": "code",
            "provider": "bifrost",
            "model": "ornith",
            "runtime": "openai",
            "base_url": "http://bifrost.internal/v1",
        }

        async def run(self, prompt, context, *, tools):
            return AgentResult.succeeded(
                {"ok": True}, summary="done", tokens_used=7, cost_micros=7
            )

    async def runtime_for(tenant_id, capability, context=None):
        return _Runtime()

    monkeypatch.setattr(spawner, "_runtime_for", runtime_for)
    res = await spawner.spawn(T, "decompose epic", ["analysis/decompose"], {}, _ctx())
    events = await kernel.store.audit_query(T, run_id=res["run_id"])
    assert events[-1].latency_ms is not None
    assert events[-1].latency_ms >= 0
    assert res["output"]["model_route"] == {
        "profile": "code",
        "provider": "bifrost",
        "model": "ornith",
        "runtime": "openai",
    }
    assert "base_url" not in events[-1].detail["model_route"]
    assert "bifrost.internal" not in repr(events[-1].detail)


@pytest.mark.invariant("FR-OBS-13")
async def test_spawn_audit_survives_observability_sink_failure(monkeypatch):
    class _FailingSink:
        async def record_spawn(self, **kwargs):
            raise RuntimeError("trace sink down")

    monkeypatch.setattr(
        "boltrig.fleet.spawn.build_observability_sink", lambda: _FailingSink()
    )
    kernel = await _kernel_with_caps()
    spawner = build_spawner(kernel)

    res = await spawner.spawn(T, "decompose epic", ["analysis/decompose"], {}, _ctx())
    events = await kernel.store.audit_query(T, run_id=res["run_id"])

    assert res["status"] == "ok"
    assert events[-1].run_id == res["run_id"]
    assert events[-1].status == "ok"
    ok, bad_seq = await kernel.audit.verify(T)
    assert (ok, bad_seq) == (True, None)


@pytest.mark.invariant("FR-OBS-13")
async def test_observability_sink_runs_after_audit_persist(monkeypatch):
    kernel = await _kernel_with_caps()
    seen: list[int] = []

    class _SpySink:
        async def record_spawn(self, **kwargs):
            events = await kernel.store.audit_query(T, run_id=kwargs["run_id"])
            seen.append(len(events))

    monkeypatch.setattr(
        "boltrig.fleet.spawn.build_observability_sink", lambda: _SpySink()
    )
    spawner = build_spawner(kernel)
    res = await spawner.spawn(T, "decompose epic", ["analysis/decompose"], {}, _ctx())

    assert res["status"] == "ok"
    assert seen == [1]
