"""Ultracode scoped memory injection and write-back."""

from __future__ import annotations

import pytest

from boltrig.fleet import build_spawner
from boltrig.fleet.hatchet_app import context_to_envelope
from boltrig.fleet.ultracode import run_ultracode_body
from boltrig.kernel import Kernel
from boltrig.memory import LocalMemoryEngine
from boltrig.memory.adapter import build_memory_adapter
from boltrig.memory.engine import EngineFact
from boltrig.memory.projections import (
    MemoryProjectionFanout,
    ProjectionRecallHit,
    ProjectionResult,
)
from boltrig.models import (
    AgentCapability,
    GrantSet,
    InvocationContext,
    MemoryFact,
    TenantPermissions,
)
from boltrig.store import InMemoryStore

T = "acme"


async def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    await store.upsert_capability(
        AgentCapability("codex-worker", T, "python-script", ["*"], 2, True, "expensive")
    )
    return Kernel(store)


def _ctx(
    run_id: str,
    *,
    workspace_id: str = "ws-1",
    on_behalf_of: str = "will",
    grants: GrantSet | None = None,
) -> InvocationContext:
    return InvocationContext(
        tenant_id=T,
        run_id=run_id,
        workspace_id=workspace_id,
        on_behalf_of=on_behalf_of,
        grants=grants or GrantSet.of(["*"]),
        actor="orchestrator",
        actor_tier="tier1",
        extra={"repo_root": "/repo"},
    )


def _payload(run_id: str, *, context: InvocationContext) -> dict:
    return {
        "tenant": T,
        "workflow": {
            "workflow_name": "remembered",
            "defaults": {"capability": "codex-worker", "memory": {"limit": 4}},
            "phases": [{"id": "phase-01", "agents": [{"id": "a", "prompt": "x"}]}],
        },
        "ctx_envelope": context_to_envelope(context),
        "run_id": run_id,
    }


def _fact(
    fid: str,
    content: str,
    *,
    workspace: str = "ws-1",
    owner_scope: str = "user:will",
) -> MemoryFact:
    return MemoryFact(
        id=fid,
        tenant_id=T,
        owner_scope=owner_scope,
        engine_ref=fid,
        kind="summary",
        source_kind="ultracode_run",
        source_ref=f"ultracode|workspace:{workspace}|run-type:ultracode",
        content=content,
    )


class _TestProjection:
    id = "cognee"

    def __init__(self):
        self.recall_calls = []

    async def remember(
        self, tenant_id: str, fact: EngineFact, context: InvocationContext
    ) -> ProjectionResult:
        return ProjectionResult.written(f"cognee:{fact.id}")

    async def recall(self, tenant_id, query, *, scopes, mode, limit, max_hops, context):
        self.recall_calls.append(
            {
                "tenant_id": tenant_id,
                "query": query,
                "scopes": list(scopes),
                "mode": mode,
                "limit": limit,
            }
        )
        return [
            ProjectionRecallHit(
                fact_id="semantic-memory",
                score=0.92,
                content="The configured projection says use the stack-owned runtime profile.",
                projection_ref="cognee:semantic-memory",
            )
        ]

    async def forget(
        self,
        tenant_id: str,
        *,
        fact_id: str,
        projection_ref: str | None,
        context: InvocationContext,
    ) -> ProjectionResult:
        return ProjectionResult.deleted(projection_ref)


@pytest.mark.invariant("FR-WFL-16")
async def test_ultracode_injects_only_scoped_memory_into_agent_prompt():
    kernel = await _kernel()
    await kernel.store.add_memory_fact(
        _fact("in-scope", "Use the checked migration order before editing auth.")
    )
    await kernel.store.add_memory_fact(
        _fact("out-scope", "This other workspace note must not appear.", workspace="other")
    )

    record = await run_ultracode_body(
        kernel,
        _payload("uc-memory", context=_ctx("uc-memory")),
        spawner=build_spawner(kernel, codex_config=None),
    )

    task = record["phases"][0]["agents"][0]["result"]["output"]["task"]
    assert "Scoped memory:" in task
    assert "Use the checked migration order" in task
    assert "other workspace note" not in task
    assert '<untrusted kind="memory.recall" source="ultracode">' in task


@pytest.mark.invariant("FR-WFL-16")
async def test_ultracode_recall_uses_the_configured_projection():
    kernel = await _kernel()
    await kernel.store.add_memory_fact(
        _fact(
            "semantic-memory",
            "Raw ledger fallback should not be injected when the projection answers.",
        )
    )
    projection = _TestProjection()
    await kernel.register_adapter(
        T,
        build_memory_adapter(
            LocalMemoryEngine(),
            kernel.store,
            audit=kernel.audit,
            config={},
            projections=MemoryProjectionFanout(
                kernel.store, [projection], primary_projection_id="cognee"
            ),
        ),
    )

    record = await run_ultracode_body(
        kernel,
        _payload("uc-projection", context=_ctx("uc-projection")),
        spawner=build_spawner(kernel, codex_config=None),
    )

    task = record["phases"][0]["agents"][0]["result"]["output"]["task"]
    assert "configured projection says" in task
    assert "Raw ledger fallback" not in task
    assert projection.recall_calls[0]["scopes"] == ["user:will", "org"]
    rows = await kernel.store.audit_query(T)
    assert any(row.verb == "memory.recall" and row.status == "ok" for row in rows)


@pytest.mark.invariant("FR-WFL-16")
async def test_ultracode_memory_injection_requires_recall_grant():
    kernel = await _kernel()
    await kernel.store.add_memory_fact(_fact("in-scope", "This memory requires the recall grant."))
    ctx = _ctx("uc-memory-denied", grants=GrantSet.of(["ticket.read"]))

    record = await run_ultracode_body(
        kernel,
        _payload("uc-memory-denied", context=ctx),
        spawner=build_spawner(kernel, codex_config=None),
    )

    task = record["phases"][0]["agents"][0]["result"]["output"]["task"]
    assert "Scoped memory:" not in task
    assert "This memory requires the recall grant" not in task


@pytest.mark.invariant("FR-WFL-16")
async def test_ultracode_stores_run_summary_through_memory_adapter():
    kernel = await _kernel()
    await kernel.register_adapter(
        T, build_memory_adapter(LocalMemoryEngine(), kernel.store, audit=kernel.audit, config={})
    )
    payload = _payload("uc-summary", context=_ctx("uc-summary"))
    payload["workflow"]["defaults"] = {"capability": "codex-worker"}

    await run_ultracode_body(
        kernel,
        payload,
        spawner=build_spawner(kernel, codex_config=None),
    )

    facts = await kernel.store.list_memory_facts(T, ["user:will"], kind="summary")
    assert len(facts) == 1
    assert facts[0].source_kind == "ultracode_run"
    assert "workspace:ws-1" in facts[0].source_ref
    assert "run:uc-summary" in facts[0].source_ref
    assert "remembered finished completed" in facts[0].content
    rows = await kernel.store.audit_query(T)
    assert any(row.verb == "memory.remember" and row.status == "ok" for row in rows)
