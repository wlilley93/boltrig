"""Self-improvement raises COMPETENCE, never AUTHORITY ([2026] VJS-COUNTY 5).

The companion to ``test_self_improvement_authority.py`` (SEC-84). Those pins prove
provenance carries no authority; these prove the surviving self-improvement legs -
library selection, harvested reuse signals, and opt-in reflection - only ever
change RANKING / likelihood and always run through the one dispatch chokepoint:

  * US-WFL-04  selection among equally-matching workflows is DETERMINISTIC and
               changes nothing about the workflow it returns.
  * US-WFL-09  a harvested free signal (regenerate-supersede / HITL verdict)
               reweights reuse via a reweight-only path, never a grant.
  * US-WFL-10  post-run reflection is opt-in and, when on, stores exactly one
               lesson through the kernel chokepoint (and none when off).

US-WFL-08, eval-gated promotion, used to sit here. It is retired in full by
[2026] VJS-CC-BOLTRIG-WORKFLOW-PROMOTION-TRIGGER-001 D3: the ranking value it
stored had no production consumer, so no tenant ever observed it. What that pin
proved and still matters - that selection is deterministic and does not touch the
workflow's executable content or authority - is re-pointed onto the surviving
matcher below.
"""
from __future__ import annotations

import dataclasses
import uuid

import pytest

from boltrig.api.bootstrap import _harvest_hitl_signal
from boltrig.fleet import (
    ChiefOfStaff,
    Department,
    DepartmentHead,
    WorkPump,
    build_org,
    build_spawner,
)
from boltrig.kernel import Kernel
from boltrig.memory import LocalMemoryEngine
from boltrig.memory.adapter import build_memory_adapter
from boltrig.models import (
    AgentCapability,
    GrantSet,
    HITLType,
    TenantPermissions,
    Urgency,
    WorkflowDefinition,
    WorkflowSource,
    WorkItem,
)
from boltrig.store import InMemoryStore
from boltrig.workflows import harvest_reuse_signal, select_or_generate_workflow
from boltrig.workflows.library import WorkflowLibrary

T = "acme"
DEPT = "engineering"

# The same authority-bearing field names SEC-84 forbids on a WorkflowDefinition.
# A reuse signal must not carry any of them either: it ranks, it does not authorise.
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


# --- US-WFL-04: selection is deterministic and changes nothing ---------------
@pytest.mark.security
@pytest.mark.invariant("US-WFL-04")
async def test_match_ranks_deterministically_and_changes_nothing():
    """The re-pointed half of the retired US-WFL-08 pin.

    The promotion subsystem is gone, so there is no second sort key any more. What
    the old pin proved and still matters is here: among workflows matching the same
    intent the matcher picks the HIGHEST overlap, then the SMALLEST id, the same way
    every time; and the workflow it hands back is byte-for-byte the one that was
    stored - selection confers no executable content and no authority (COUNTY 5).
    """
    store = InMemoryStore()
    await store.upsert_workflow(_wf("wf-b"))
    await store.upsert_workflow(_wf("wf-a"))

    # equal overlap -> smallest id, and it is stable across repeated calls.
    for _ in range(3):
        picked = await select_or_generate_workflow(store, "a billing run", ["billing"], T)
        assert picked.id == "wf-a"

    # higher overlap beats the id tiebreak: wf-z shares two tags, wf-a shares one.
    wide = dataclasses.replace(_wf("wf-z"), intent_tags=["billing", "invoice"])
    await store.upsert_workflow(wide)
    best = await select_or_generate_workflow(
        store, "a billing run", ["billing", "invoice"], T
    )
    assert best.id == "wf-z"

    # selection did not add executable content, provenance or authority to what it
    # returned - it is the stored definition, unchanged (competence, not power).
    reread = await WorkflowLibrary(store).get(T, "wf-a")
    assert reread.definition == {"name": "wf-a", "steps": []}
    assert reread.source is WorkflowSource.LEARNED
    assert {f.name for f in dataclasses.fields(WorkflowDefinition)} & _AUTHORITY_BEARING == set()


# --- US-WFL-09: harvested signals reweight reuse, never authority ------------
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


@pytest.mark.security
@pytest.mark.invariant("US-WFL-09")
async def test_only_approval_verdicts_are_harvested_as_reuse_signals():
    kernel = _kernel()
    seen: list[dict] = []

    async def record_invoke(noun, verb, params, context, **kwargs):
        seen.append(params)
        return {"adjusted": True}

    kernel.invoke = record_invoke
    clarification = await kernel.hitl.create(
        tenant_id=T,
        run_id="run-clarification",
        type=HITLType.CLARIFICATION,
        question="Which region?",
        urgency=Urgency.BLOCKING,
        requested_by="agent",
    )
    await kernel.hitl.answer(T, clarification.id, "continue", "reviewer")
    await _harvest_hitl_signal(kernel, clarification)
    assert seen == []

    approval = await kernel.hitl.create(
        tenant_id=T,
        run_id="run-approval",
        type=HITLType.APPROVAL,
        question="Approve?",
        verb="ticket.create",
        requested_by="agent",
        request_fingerprint="fingerprint",
    )
    await kernel.hitl.answer(T, approval.id, "approve", "reviewer")
    await _harvest_hitl_signal(kernel, approval)
    assert seen == [
        {"signal": "hitl_verdict:endorsement", "target": "run-approval"}
    ]

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
    # Decision 0029: the same terminal run also proposes ONE typed episode
    # (memory.propose, same seat, same opt-in gate) whose retrieval text
    # embeds the problem representation - the intent and how it ended - never
    # a resolution alone.
    episodes = await kernel.store.list_memory_facts(T, ["user:chief-of-staff"], kind="episodic")
    assert len(episodes) == 1
    retrieval = (episodes[0].payload or {}).get("retrieval_text", "")
    assert "close the ticket" in retrieval and "ended as done" in retrieval
    assert (episodes[0].payload or {}).get("outcome") == "succeeded"
    assert episodes[0].status == "active"
    assert any(r.verb == "memory.propose" and r.status == "ok" for r in rows)

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
