"""Boltrig v2 Ultracode phased workflow runner."""

import pytest

from boltrig.fleet.hatchet_app import (
    TASK_ULTRACODE_AGENT,
    TASK_ULTRACODE_RUN,
    context_to_envelope,
    register_boltrig_tasks,
)
from boltrig.fleet.hatchet_ultracode import _hatchet_ultracode_agent_runner
from boltrig.fleet.ultracode import UltracodeSpecError, run_ultracode_body, validate_workflow
from boltrig.fleet.workers import LocalDurableExecutor
from boltrig.kernel import Kernel
from boltrig.models import (
    AgentCapability,
    GrantSet,
    InvocationContext,
    TenantPermissions,
)
from boltrig.store import InMemoryStore

T = "acme"


async def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    await store.upsert_capability(
        AgentCapability("script-worker", T, "python-script", ["*"], 2, True, "cheap")
    )
    await store.upsert_capability(
        AgentCapability("opencode-worker", T, "python-script", ["*"], 2, True, "expensive")
    )
    return Kernel(store)


def _ctx(
    run_id: str = "uc-run",
    *,
    workspace_id: str | None = None,
    on_behalf_of: str | None = None,
    extra: dict | None = None,
) -> InvocationContext:
    return InvocationContext(
        tenant_id=T,
        run_id=run_id,
        workspace_id=workspace_id,
        on_behalf_of=on_behalf_of,
        grants=GrantSet.of(["*"]),
        actor="orchestrator",
        actor_tier="tier1",
        extra={"repo_root": "/repo", **(extra or {})},
    )


def _workflow() -> dict:
    return {
        "workflow_name": "demo",
        "goal": "Use phased agents to inspect and then plan.",
        "defaults": {"capability": "opencode-worker", "max_total_agents": 4},
        "phases": [
            {
                "id": "phase-01-discovery",
                "name": "Discovery",
                "concurrency": 2,
                "agents": [
                    {"id": "map", "prompt": "Map the repository."},
                    {"id": "risk", "objective": "Find risks."},
                ],
            },
            {
                "id": "phase-02-plan",
                "depends_on": ["phase-01-discovery"],
                "agents": [{"id": "plan", "prompt": "Synthesize the plan."}],
            },
        ],
    }

@pytest.mark.invariant("FR-WFL-12")
def test_ultracode_validation_rejects_missing_prompt():
    with pytest.raises(UltracodeSpecError):
        validate_workflow({"phases": [{"id": "phase-01", "agents": [{"id": "a"}]}]})


@pytest.mark.invariant("FR-WFL-12")
def test_ultracode_validation_rejects_excessive_concurrency():
    with pytest.raises(UltracodeSpecError, match="max_phase_concurrency"):
        validate_workflow({
            "defaults": {"max_phase_concurrency": 1},
            "phases": [{"id": "phase-01", "concurrency": 2,
                        "agents": [{"id": "a", "prompt": "x"}]}],
        })


@pytest.mark.invariant("FR-WFL-13")
async def test_ultracode_run_executes_phases_through_preferred_capability():
    kernel = await _kernel()
    payload = {
        "tenant": T,
        "workflow": _workflow(),
        "ctx_envelope": context_to_envelope(_ctx()),
        "run_id": "uc-run",
    }

    record = await run_ultracode_body(kernel, payload)

    assert record["status"] == "completed"
    assert [phase["id"] for phase in record["phases"]] == [
        "phase-01-discovery", "phase-02-plan",
    ]
    agents = [agent for phase in record["phases"] for agent in phase["agents"]]
    assert {agent["result"]["agent_type"] for agent in agents} == {"opencode-worker"}
    checkpoints = {
        c.step: c.status for c in await kernel.store.list_checkpoints(T, "uc-run")
    }
    assert checkpoints == {
        "ultracode:phase-01-discovery": "completed",
        "ultracode:phase-02-plan": "completed",
        "ultracode:phase-01-discovery:map": "completed",
        "ultracode:phase-01-discovery:risk": "completed",
        "ultracode:phase-02-plan:plan": "completed",
    }
    assert any(
        e.get("status") == "phase_finished" for e in kernel.events.snapshot(T, "uc-run")
    )


@pytest.mark.invariant("FR-WFL-13")
async def test_mastra_plan_payload_compiles_and_runs_through_ultracode_spine():
    kernel = await _kernel()
    payload = {
        "tenant": T,
        "mastra_plan": {
            "name": "mastra-demo",
            "goal": "Plan from a graph-shaped orchestration contract.",
            "defaults": {"capability": "opencode-worker", "max_total_agents": 3},
            "steps": [
                {"id": "discover", "agents": [
                    {"id": "map", "instructions": "Map the repo."}
                ]},
                {"id": "plan", "after": ["discover"], "agents": [
                    {"id": "synth", "instructions": "Synthesize a plan."}
                ]},
            ],
        },
        "ctx_envelope": context_to_envelope(_ctx("mastra-run")),
        "run_id": "mastra-run",
    }

    record = await run_ultracode_body(kernel, payload)

    assert record["workflow_name"] == "mastra-demo"
    assert record["status"] == "completed"
    assert [phase["id"] for phase in record["phases"]] == ["discover", "plan"]
    checkpoints = {
        c.step: c.status for c in await kernel.store.list_checkpoints(T, "mastra-run")
    }
    assert checkpoints["ultracode:discover:map"] == "completed"
    assert checkpoints["ultracode:plan:synth"] == "completed"


@pytest.mark.invariant("FR-WFL-14")
async def test_ultracode_run_registered_on_local_durable_executor():
    kernel = await _kernel()
    executor = LocalDurableExecutor()
    register_boltrig_tasks(executor, kernel)
    payload = {
        "tenant": T,
        "workflow": {"phases": [{"id": "phase-01", "agents": [{"id": "a", "prompt": "x"}]}]},
        "ctx_envelope": context_to_envelope(_ctx("uc-local")),
        "run_id": "uc-local",
    }

    await executor.enqueue(TASK_ULTRACODE_RUN, payload)

    assert [step.name for step in executor.steps] == [
        f"task:{TASK_ULTRACODE_RUN}",
        f"task:{TASK_ULTRACODE_AGENT}:phase-01:a",
    ]
    checkpoints = await kernel.store.list_checkpoints(T, "uc-local")
    assert [(c.step, c.status) for c in checkpoints] == [
        ("ultracode:phase-01:a", "completed"),
        ("ultracode:phase-01", "completed"),
    ]


@pytest.mark.invariant("FR-WFL-15")
async def test_ultracode_replays_completed_phase_checkpoint():
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    phase_record = {
        "id": "phase-01",
        "status": "completed",
        "agents": [{"id": "a", "status": "ok", "degraded": False, "result": {}}],
    }
    await store.upsert_checkpoint(
        T, "uc-replay", "ultracode:phase-01", "completed", output=phase_record
    )
    kernel = Kernel(store)
    payload = {
        "tenant": T,
        "workflow": {"phases": [{"id": "phase-01", "agents": [{"id": "a", "prompt": "x"}]}]},
        "ctx_envelope": context_to_envelope(_ctx("uc-replay")),
        "run_id": "uc-replay",
    }

    record = await run_ultracode_body(kernel, payload)

    assert record["status"] == "completed"
    assert record["phases"] == [phase_record]
    assert any(
        e.get("status") == "phase_replayed" for e in kernel.events.snapshot(T, "uc-replay")
    )


@pytest.mark.invariant("FR-WFL-15")
async def test_ultracode_replays_completed_agent_checkpoint():
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    agent_record = {"id": "a", "status": "ok", "degraded": False, "result": {}}
    await store.upsert_checkpoint(
        T, "uc-agent-replay", "ultracode:phase-01:a", "completed", output=agent_record
    )
    kernel = Kernel(store)
    payload = {
        "tenant": T,
        "workflow": {"phases": [{"id": "phase-01", "agents": [{"id": "a", "prompt": "x"}]}]},
        "ctx_envelope": context_to_envelope(_ctx("uc-agent-replay")),
        "run_id": "uc-agent-replay",
    }

    record = await run_ultracode_body(kernel, payload)

    assert record["status"] == "completed"
    assert record["phases"][0]["agents"] == [agent_record]
    checkpoints = {
        c.step: c.status for c in await kernel.store.list_checkpoints(T, "uc-agent-replay")
    }
    assert checkpoints == {
        "ultracode:phase-01:a": "completed",
        "ultracode:phase-01": "completed",
    }


@pytest.mark.invariant("FR-WFL-15")
async def test_hatchet_child_runner_uses_registered_agent_task():
    class _Workflow:
        def __init__(self) -> None:
            self.payload = None

        async def aio_run(self, payload):
            self.payload = payload
            return {"id": "a", "status": "ok", "degraded": False, "result": {}}

    async def inline(_payload):
        raise AssertionError("inline runner should not be used when child API exists")

    workflow = _Workflow()
    payload = {
        "tenant": T,
        "run_id": "uc-child",
        "phase": {"id": "phase-01"},
        "agent": {"id": "a"},
        "ctx_envelope": context_to_envelope(_ctx("uc-child")),
    }

    record = await _hatchet_ultracode_agent_runner(workflow, payload, inline)

    assert record["id"] == "a"
    assert workflow.payload["run_id"] == "uc-child"
    assert workflow.payload["agent"]["id"] == "a"
