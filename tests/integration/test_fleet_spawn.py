"""Ephemeral spawn: cheapest-capable selection, depth + context guards (Epic FLT)."""

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
        AgentCapability("codex-expensive", T, "codex", ["*"], 2, True, "expensive")
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
    # The script receipt remains available to non-Chat orchestration and audit;
    # only the direct Chat projection replaces it with user-facing degraded copy.
    assert res["summary"] == "script run by script-worker (depth 1)"


@pytest.mark.invariant("SEC-147")
async def test_every_spawn_caps_skill_requirements_to_parent_authority():
    kernel = await _kernel_with_caps()
    spawner = build_spawner(kernel)
    parent = _ctx()
    parent = InvocationContext(
        tenant_id=parent.tenant_id,
        grants=GrantSet.of(["other.read"]),
        actor=parent.actor,
        extra=parent.extra,
    )

    res = await spawner.spawn(T, "decompose epic", ["analysis/decompose"], {}, parent)

    assert res["effective_grants"] == []
    assert res["output"]["tools"] == []


@pytest.mark.invariant("US-FLT-04")
async def test_preferred_capability_chosen_when_capable():
    kernel = await _kernel_with_caps()
    spawner = build_spawner(kernel)
    res = await spawner.spawn(
        T, "decompose epic", ["analysis/decompose"],
        {"capability": "preferred-script"}, _ctx(),
    )
    assert res["agent_type"] == "preferred-script"


async def test_preferred_runtime_is_honoured_over_cost_order():
    kernel = await _kernel_with_caps()
    spawner = build_spawner(kernel)

    res = await spawner.spawn(
        T,
        "decompose epic",
        ["analysis/decompose"],
        {"runtime": "codex"},
        _ctx(),
    )

    assert res["agent_type"] == "codex-expensive"


async def test_script_runtime_alias_selects_python_script_capability():
    kernel = await _kernel_with_caps()
    spawner = build_spawner(kernel)

    res = await spawner.spawn(
        T,
        "decompose epic",
        ["analysis/decompose"],
        {"runtime": "script"},
        _ctx(),
    )

    assert res["agent_type"] == "script-worker"


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


@pytest.mark.invariant("US-FLT-04")
@pytest.mark.invariant("SEC-WRK-10")
async def test_subagent_open_is_settled_by_subagent_end_frame(monkeypatch):
    """G3 (SDK-CONTRACT §5): a subagent open frame is paired with a subagent_end
    carrying the SAME child_run_id on the SAME parent relay, so a consumer's
    delegation tree settles instead of rendering the child RUNNING forever."""
    kernel = await _kernel_with_caps()
    published: list[tuple[str, dict]] = []
    real_publish = kernel.events.publish

    def capture(tenant_id, stream_id, event):
        published.append((stream_id, event))
        return real_publish(tenant_id, stream_id, event)

    monkeypatch.setattr(kernel.events, "publish", capture)
    spawner = build_spawner(kernel)
    parent = InvocationContext(
        tenant_id=T, run_id="parent-run", grants=GrantSet.of(["*"]),
        actor="head", extra={"epic_id": "ENG-441"},
    )
    res = await spawner.spawn(T, "decompose epic", ["analysis/decompose"], {}, parent)

    opens = [e for sid, e in published if sid == "parent-run" and e.get("type") == "subagent"]
    ends = [e for sid, e in published if sid == "parent-run" and e.get("type") == "subagent_end"]
    assert len(opens) == 1 and len(ends) == 1
    # paired to the SAME child run id the open announced
    assert opens[0]["child_run_id"] == res["run_id"] == ends[0]["child_run_id"]
    assert opens[0]["name"] == opens[0]["capability"]
    assert opens[0]["familiar_genotype"]["source"] == (
        "agent_capability.name.v1"
    )
    assert not {
        "grants",
        "runtime",
        "model_endpoint",
        "phenotype",
        "mood",
    } & set(opens[0]["familiar_genotype"])
    assert ends[0]["status"] in {"ok", "degraded"}
