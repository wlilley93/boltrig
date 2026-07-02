"""The learning-loop flywheel: scoring, learning, retrieval, reflection (Phase 3).

The engine audit found no closed learning loop: ``learn_from_success`` and
``library.match`` both existed but were UNCALLED, and there was zero post-run
reflection or outcome scoring. These tests pin the wiring that closes it:

  * a terminal item is scored deterministically (US-WFL-06);
  * a succeeded, synthesised workflow is re-saved as learned (US-WFL-03);
  * generation prefers a matching learned workflow before synthesising (US-WFL-04);
  * a bounded reflection distils a lesson through the memory verb - governed by the
    one chokepoint - and never fails the run (US-WFL-07).

Everything runs offline: the ScriptRuntime child is deterministic, the hermes
capability without an endpoint degrades (P9), and reflection uses the LocalMemory
engine behind the real MemoryAdapter, so the governance screens run for real.
"""

from __future__ import annotations

import uuid

import pytest

from boltrig.fleet import (
    ChiefOfStaff,
    Department,
    DepartmentHead,
    WorkPump,
    build_spawner,
)
from boltrig.kernel import Kernel
from boltrig.memory import LocalMemoryEngine
from boltrig.memory.adapter import build_memory_adapter
from boltrig.models import (
    AgentCapability,
    GrantSet,
    TenantPermissions,
    WorkflowDefinition,
    WorkflowSource,
    WorkItem,
    WorkStatus,
)
from boltrig.store import InMemoryStore
from boltrig.workflows import select_or_generate_workflow

T = "acme"
DEPT = "engineering"


def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    return Kernel(store)


async def _add_script_cap(kernel: Kernel) -> None:
    await kernel.store.upsert_capability(
        AgentCapability("script-worker", T, "python-script", ["*"], 3, True, "cheap")
    )


async def _add_hermes_cap(kernel: Kernel) -> None:
    # hermes with no endpoint degrades every child instead of reasoning (P9).
    await kernel.store.upsert_capability(
        AgentCapability("hermes-worker", T, "hermes", ["*"], 3, True, "standard")
    )


def _item(intent: str = "fix the login bug", **kw) -> WorkItem:
    return WorkItem(
        id=uuid.uuid4().hex,
        tenant_id=T,
        source="internal",
        intent=intent,
        confidence=0.9,
        convergent=kw.pop("convergent", False),
        **kw,
    )


def _pump(kernel: Kernel, *, heads=None, max_attempts=3, reflect=None):
    spawner = build_spawner(kernel)
    if heads is None:
        heads = {DEPT: DepartmentHead(DEPT, [], [], 32, spawner=spawner, store=kernel.store)}
    cos = ChiefOfStaff(kernel, [Department(DEPT, intent_keywords=["bug", "fix"])])
    return WorkPump(
        kernel, spawner, cos, heads, None, max_attempts=max_attempts, reflect=reflect
    )


# --- US-WFL-06: a terminal item is scored deterministically ------------------
@pytest.mark.invariant("US-WFL-06")
async def test_terminal_item_records_outcome_score():
    # (a) a clean, non-degraded success scores 1.0
    kernel = _kernel()
    await _add_script_cap(kernel)
    clean = _item("fix the login bug")
    await kernel.store.create_work_item(clean)
    assert await _pump(kernel).run_once(T) is True
    done = await kernel.store.get_work_item(T, clean.id)
    assert done.status == WorkStatus.DONE and done.degraded is False
    assert done.result["outcome"] == {
        "score": 1.0, "terminal_status": "done", "degraded": False,
    }

    # (b) a degraded (but non-convergent) success scores 0.5
    kernel2 = _kernel()
    await _add_hermes_cap(kernel2)
    degraded = _item("do the degraded thing", convergent=False)
    await kernel2.store.create_work_item(degraded)
    assert await _pump(kernel2).run_once(T) is True
    d = await kernel2.store.get_work_item(T, degraded.id)
    assert d.status == WorkStatus.DONE and d.degraded is True
    assert d.result["outcome"]["score"] == 0.5
    assert d.result["outcome"]["degraded"] is True

    # (c) a failed item scores 0.0
    class _ExplodingHead:
        name = DEPT

        async def handle(self, work_item, context, *, prefer=None, tree_id=None):
            raise RuntimeError("boom")

    kernel3 = _kernel()
    failed = _item("this will fail")
    await kernel3.store.create_work_item(failed)
    assert await _pump(kernel3, heads={DEPT: _ExplodingHead()}, max_attempts=1).run_once(T)
    f = await kernel3.store.get_work_item(T, failed.id)
    assert f.status == WorkStatus.FAILED
    assert f.result["outcome"] == {
        "score": 0.0, "terminal_status": "failed", "degraded": False,
    }
    # the error detail is preserved alongside the outcome (not clobbered)
    assert f.result["error"] == "RuntimeError"


# --- US-WFL-03: a succeeded synthesised workflow is learned -------------------
@pytest.mark.invariant("US-WFL-03")
async def test_successful_generated_workflow_is_learned():
    from boltrig.workflows import generate_workflow

    # a stub head whose completion carries a synthesised (GENERATED) workflow -
    # the smallest hook proving the generate -> run -> learn wiring (full path
    # completes when workflow synthesis is on the delegation path).
    wf = generate_workflow("process the billing run", ["billing"], T)
    assert wf.source == WorkflowSource.GENERATED

    class _WorkflowHead:
        name = DEPT

        async def handle(self, work_item, context, *, prefer=None, tree_id=None):
            return {
                "status": "ok", "department": self.name,
                "work_item_id": work_item.id, "children": [], "spawned": 0,
                "new_work_items": [], "generated_workflow": wf,
            }

    kernel = _kernel()
    item = _item("process the billing run")
    await kernel.store.create_work_item(item)
    assert await _pump(kernel, heads={DEPT: _WorkflowHead()}).run_once(T) is True

    done = await kernel.store.get_work_item(T, item.id)
    assert done.status == WorkStatus.DONE
    assert done.result["outcome"]["score"] == 1.0
    # the workflow was re-saved as learned (same id, source flipped) - the retrieval
    # half can now reuse it next time.
    stored = await kernel.store.list_workflows(T)
    assert [w.source for w in stored] == [WorkflowSource.LEARNED]
    assert stored[0].id == wf.id
    assert stored[0].origin_task == item.intent


# --- US-WFL-04: generation prefers a learned match ---------------------------
@pytest.mark.invariant("US-WFL-04")
async def test_generation_prefers_a_learned_match():
    store = InMemoryStore()
    learned = WorkflowDefinition(
        id="learned-billing", tenant_id=T, version="1.0.0",
        source=WorkflowSource.LEARNED,
        definition={"name": "learned-billing", "steps": []},
        intent_tags=["billing"], origin_task="a prior billing success",
    )
    await store.upsert_workflow(learned)

    # a matching intent reuses the learned workflow instead of synthesising
    chosen = await select_or_generate_workflow(
        store, "handle a fresh billing run", ["billing"], T
    )
    assert chosen.id == "learned-billing"
    assert chosen.source == WorkflowSource.LEARNED

    # an empty / non-matching library still synthesises as before (behaviour kept)
    empty = InMemoryStore()
    synthesised = await select_or_generate_workflow(empty, "do a thing", ["misc"], T)
    assert synthesised.source == WorkflowSource.GENERATED
    assert synthesised.id.startswith("gen-")


# --- US-WFL-07: reflection is governed through the chokepoint and best-effort -
@pytest.mark.invariant("US-WFL-07")
async def test_reflection_is_governed_and_best_effort():
    # governed: reflection writes THROUGH kernel.invoke -> the memory adapter, so
    # the fact carries provenance and the write is audited on the chokepoint.
    kernel = _kernel()
    await _add_script_cap(kernel)
    engine = LocalMemoryEngine()
    await kernel.register_adapter(
        T, build_memory_adapter(engine, kernel.store, audit=kernel.audit, config={}),
    )
    item = _item("close the ticket")
    await kernel.store.create_work_item(item)
    assert await _pump(kernel, reflect=True).run_once(T) is True

    done = await kernel.store.get_work_item(T, item.id)
    assert done.status == WorkStatus.DONE
    facts = await kernel.store.list_memory_facts(T, ["user:chief-of-staff"], kind="lesson")
    assert len(facts) == 1
    # provenance: the lesson is tagged as a reflection carrying the run id
    assert facts[0].source_kind == "reflection"
    assert facts[0].source_ref == item.id
    # governed: the memory.remember call rode the chokepoint (audited)
    rows = await kernel.store.audit_query(T)
    assert any(r.verb == "memory.remember" and r.status == "ok" for r in rows)

    # best-effort: a raising memory call does not fail the item (P9)
    kernel2 = _kernel()
    await _add_script_cap(kernel2)
    pump2 = _pump(kernel2, reflect=True)

    class _RaisingKernel:
        def __init__(self) -> None:
            self.calls = 0

        async def invoke(self, *args, **kwargs):
            self.calls += 1
            raise RuntimeError("memory backend down")

    raising = _RaisingKernel()
    pump2._kernel = raising  # the reflection target raises on every call
    item2 = _item("close the other ticket")
    await kernel2.store.create_work_item(item2)
    assert await pump2.run_once(T) is True
    survived = await kernel2.store.get_work_item(T, item2.id)
    # the reflection was attempted and raised, yet the item still completed
    assert raising.calls >= 1
    assert survived.status == WorkStatus.DONE
    assert survived.result["outcome"]["score"] == 1.0
