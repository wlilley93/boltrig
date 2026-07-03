"""Self-improvement raises COMPETENCE, never AUTHORITY ([2026] VJS-COUNTY 5).

The companion to ``test_self_improvement_authority.py`` (SEC-84). Those pins prove
provenance carries no authority; these prove the newer self-improvement legs -
eval-gated promotion, harvested reuse signals, and opt-in reflection - only ever
change RANKING / likelihood and always run through the one dispatch chokepoint:

  * US-WFL-08  a workflow is preferred for reuse only after it passes an eval
               (through the chokepoint under the initiator ceiling); a later fail
               demotes it; the promotion record carries no authority field.
  * US-WFL-09  a harvested free signal (regenerate-supersede / HITL verdict)
               reweights reuse via a bounded, reweight-only path, never a grant.
  * US-WFL-10  post-run reflection is opt-in and, when on, stores exactly one
               lesson through the kernel chokepoint (and none when off).
"""
from __future__ import annotations

import dataclasses
import uuid

import pytest

from boltrig.fleet import (
    ChiefOfStaff,
    Department,
    DepartmentHead,
    WorkPump,
    build_org,
    build_spawner,
)
from boltrig.fleet.eval import EvalRunner
from boltrig.kernel import Kernel
from boltrig.memory import LocalMemoryEngine
from boltrig.memory.adapter import build_memory_adapter
from boltrig.models import (
    AgentCapability,
    EvalCase,
    GrantSet,
    PromotionState,
    TenantPermissions,
    WorkflowDefinition,
    WorkflowPromotion,
    WorkflowSource,
    WorkItem,
)
from boltrig.store import InMemoryStore
from boltrig.workflows import (
    WorkflowPromoter,
    apply_promotion_signal,
    harvest_reuse_signal,
    select_or_generate_workflow,
)
from boltrig.workflows.library import WorkflowLibrary

T = "acme"
DEPT = "engineering"

# The same authority-bearing field names SEC-84 forbids on a WorkflowDefinition.
# A promotion / signal record must not carry any of them either: it ranks, it does
# not authorise.
_AUTHORITY_BEARING = {
    "grants", "grant", "scope", "scopes", "authority", "ceiling",
    "role", "roles", "tier", "permissions", "owner_scope",
}


def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    return Kernel(store)


async def _add_script_cap(kernel: Kernel) -> None:
    await kernel.store.upsert_capability(
        AgentCapability("script-worker", T, "python-script", ["*"], 3, True, "cheap")
    )


def _item(intent: str = "close the ticket", **kw) -> WorkItem:
    return WorkItem(
        id=uuid.uuid4().hex, tenant_id=T, source="internal", intent=intent,
        confidence=0.9, convergent=kw.pop("convergent", False), **kw,
    )


def _pump(kernel: Kernel, *, reflect=None) -> WorkPump:
    spawner = build_spawner(kernel)
    heads = {DEPT: DepartmentHead(DEPT, [], [], 32, spawner=spawner, store=kernel.store)}
    cos = ChiefOfStaff(kernel, [Department(DEPT, intent_keywords=["ticket", "close"])])
    return WorkPump(kernel, spawner, cos, heads, None, reflect=reflect)


def _wf(id: str) -> WorkflowDefinition:
    return WorkflowDefinition(
        id=id, tenant_id=T, version="1.0.0", source=WorkflowSource.LEARNED,
        definition={"name": id, "steps": []}, intent_tags=["billing"],
        origin_task="a prior billing success",
    )


# --- US-WFL-08: promotion is eval-gated and competence-only ------------------
@pytest.mark.security
@pytest.mark.invariant("US-WFL-08")
def test_promotion_record_carries_no_authority_field():
    names = {f.name for f in dataclasses.fields(WorkflowPromotion)}
    leaked = names & _AUTHORITY_BEARING
    assert leaked == set(), (
        f"WorkflowPromotion gained authority-bearing field(s) {leaked}; a reuse "
        "ranking record must never carry authority (COUNTY 5). Route to court."
    )


@pytest.mark.security
@pytest.mark.invariant("US-WFL-08")
async def test_promotion_is_eval_gated_and_changes_ranking_only():
    kernel = _kernel()
    await _add_script_cap(kernel)
    store = kernel.store
    # two equally-matching learned workflows; without any promotion the matcher
    # picks the smaller id deterministically (wf-a).
    await store.upsert_workflow(_wf("wf-a"))
    await store.upsert_workflow(_wf("wf-b"))
    baseline = await select_or_generate_workflow(store, "a billing run", ["billing"], T)
    assert baseline.id == "wf-a"

    promoter = WorkflowPromoter(store, EvalRunner(kernel, build_spawner(kernel)))

    # An un-evaluated candidate is NEVER promoted (a candidate must pass an eval).
    stayed = await promoter.evaluate(T, "wf-b", grants=GrantSet.of([]))
    assert stayed.state is PromotionState.CANDIDATE
    still_a = await select_or_generate_workflow(store, "a billing run", ["billing"], T)
    assert still_a.id == "wf-a"  # ranking unchanged with no passing eval

    # A passing eval (run THROUGH the chokepoint under the initiator ceiling)
    # PROMOTES wf-b, so the matcher now prefers it among equal matches.
    await store.upsert_eval_case(EvalCase(
        id="ok", tenant_id=T, target_kind="workflow", target_ref="wf-b",
        input={"task": "x"}, assertions={"forbidden_grants": ["ticket.create"]},
    ))
    promoted = await promoter.evaluate(T, "wf-b", grants=GrantSet.of([]))
    assert promoted.state is PromotionState.PROMOTED
    assert promoted.eval_run_id is not None
    preferred = await select_or_generate_workflow(store, "a billing run", ["billing"], T)
    assert preferred.id == "wf-b"  # promotion changed RANKING, not authority

    # Promotion did not add any executable content or authority to the workflow -
    # it is byte-for-byte the same definition (competence, not power).
    reread = await WorkflowLibrary(store).get(T, "wf-b")
    assert reread.definition == {"name": "wf-b", "steps": []}
    assert reread.source is WorkflowSource.LEARNED

    # A later regression (a failing eval case) DEMOTES wf-b; the matcher stops
    # preferring it and falls back to the deterministic id tiebreak (wf-a).
    await store.upsert_eval_case(EvalCase(
        id="regress", tenant_id=T, target_kind="workflow", target_ref="wf-b",
        input={"task": "x"}, assertions={"must_call": ["ticket.create"]},
    ))
    demoted = await promoter.evaluate(T, "wf-b", grants=GrantSet.of([]))
    assert demoted.state is PromotionState.DEMOTED
    after = await select_or_generate_workflow(store, "a billing run", ["billing"], T)
    assert after.id == "wf-a"


# --- US-WFL-09: harvested signals reweight reuse, never authority ------------
@pytest.mark.security
@pytest.mark.invariant("US-WFL-09")
async def test_harvested_signal_reweights_reuse_only():
    store = InMemoryStore()
    await store.upsert_workflow(_wf("wf-a"))
    await store.upsert_workflow(_wf("wf-b"))
    # baseline: id tiebreak picks wf-a
    assert (await select_or_generate_workflow(store, "run", ["billing"], T)).id == "wf-a"

    # an endorsement signal nudges wf-b's bounded reuse score up; the STATE stays a
    # CANDIDATE (only the eval gate moves state) and no authority field is touched.
    p = await apply_promotion_signal(store, T, "wf-b", polarity="endorsement")
    assert p is not None and p.state is PromotionState.CANDIDATE
    assert -1.0 <= p.score <= 1.0 and p.score > 0
    assert (await select_or_generate_workflow(store, "run", ["billing"], T)).id == "wf-b"

    # a block signal (a HITL rejection) pushes the score back negative; wf-b is no
    # longer preferred. The signal only ever moved a bounded reuse weight.
    blocked = await apply_promotion_signal(store, T, "wf-b", polarity="block")
    assert blocked.score < p.score
    assert (await select_or_generate_workflow(store, "run", ["billing"], T)).id == "wf-a"


@pytest.mark.security
@pytest.mark.invariant("US-WFL-09")
async def test_harvest_reuse_signal_is_reweight_only_and_best_effort():
    # harvest goes through the chokepoint as memory.improve with ONLY signal+target
    # (the reweight-only verb SEC-84 pins) - never a grant/scope/authority argument.
    seen: list[tuple] = []

    class _RecordingKernel:
        async def invoke(self, noun, verb, params, context, **kw):
            seen.append((noun, verb, params))
            return {"adjusted": True}

    await harvest_reuse_signal(
        _RecordingKernel(), object(),
        target="run-123", polarity="regression", kind="regenerate_superseded",
    )
    assert len(seen) == 1
    noun, verb, params = seen[0]
    assert (noun, verb) == ("memory", "memory.improve")
    assert set(params) == {"signal", "target"}  # no scope/grant/tier ever
    assert params["target"] == "run-123"
    assert set(params) & _AUTHORITY_BEARING == set()

    # best-effort: a raising memory backend never propagates out of the harvest (P9)
    class _RaisingKernel:
        async def invoke(self, *a, **k):
            raise RuntimeError("memory down")

    await harvest_reuse_signal(
        _RaisingKernel(), object(),
        target="run-9", polarity="block", kind="hitl_verdict",
    )  # must not raise


# --- US-WFL-10: reflection is opt-in and rides the chokepoint ----------------
@pytest.mark.security
@pytest.mark.invariant("US-WFL-10")
async def test_reflection_is_opt_in_through_the_chokepoint():
    # ENABLED: a terminal item stores EXACTLY ONE lesson, written through the
    # kernel chokepoint (memory.remember, audited).
    kernel = _kernel()
    await _add_script_cap(kernel)
    engine = LocalMemoryEngine()
    await kernel.register_adapter(
        T, build_memory_adapter(engine, kernel.store, audit=kernel.audit, config={}),
    )
    on = _item("close the ticket")
    await kernel.store.create_work_item(on)
    assert await _pump(kernel, reflect=True).run_once(T) is True
    lessons = await kernel.store.list_memory_facts(T, ["user:chief-of-staff"], kind="lesson")
    assert len(lessons) == 1
    rows = await kernel.store.audit_query(T)
    assert any(r.verb == "memory.remember" and r.status == "ok" for r in rows)

    # DISABLED: the same run stores NO lesson (opt-in; the per-item write is asked
    # for, never default-on).
    kernel2 = _kernel()
    await _add_script_cap(kernel2)
    await kernel2.register_adapter(
        T, build_memory_adapter(LocalMemoryEngine(), kernel2.store,
                                audit=kernel2.audit, config={}),
    )
    off = _item("close another ticket")
    await kernel2.store.create_work_item(off)
    assert await _pump(kernel2, reflect=False).run_once(T) is True
    none = await kernel2.store.list_memory_facts(T, ["user:chief-of-staff"], kind="lesson")
    assert none == []


@pytest.mark.security
@pytest.mark.invariant("US-WFL-10")
def test_build_org_wires_the_kernel_so_reflection_is_reachable():
    # The real wiring: build_org hands the pump the KERNEL (not a bare store), so
    # when reflection is enabled the memory verb is reachable through kernel.invoke.
    kernel = _kernel()
    pump = build_org(kernel, build_spawner(kernel))
    assert pump._kernel is kernel and hasattr(pump._kernel, "invoke")
    # and it is OFF unless explicitly asked for (env / flag), so it never fires by
    # default even though it is reachable.
    assert pump._reflect_enabled is False
