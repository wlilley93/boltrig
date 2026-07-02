"""The delegation pump: the org goes live (Beat 4; US-FLT-06, US-EXE-06/07, D6).

Everything runs offline: the ScriptRuntime children are deterministic, the
hermes capability without an endpoint degrades (P9), and decomposition width is
driven by a stub runtime returning a fixed subtask list.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from boltrig.fleet import (
    ChiefOfStaff,
    Department,
    DepartmentHead,
    LocalDurableExecutor,
    WorkPump,
    build_org,
    build_spawner,
)
from boltrig.fleet.chat import ChatService, build_turn_executor
from boltrig.fleet.result import AgentResult
from boltrig.kernel import Kernel
from boltrig.kernel.events import EventRelay
from boltrig.models import (
    ActionType,
    AgentCapability,
    GrantSet,
    TenantPermissions,
    WorkItem,
    WorkStatus,
)
from boltrig.store import InMemoryStore

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


class _FanoutRuntime:
    """A decomposition stub: every step splits into ``n`` sub-tasks."""

    def __init__(self, n: int) -> None:
        self.n = n

    async def run(self, prompt, context, *, tools):
        return AgentResult.succeeded({"subtasks": [f"sub-task {i}" for i in range(self.n)]})


def _pump(kernel: Kernel, *, heads=None, executor=None, max_attempts=3, head_kwargs=None):
    spawner = build_spawner(kernel)
    if heads is None:
        heads = {
            DEPT: DepartmentHead(
                DEPT, [], [], 32, spawner=spawner, store=kernel.store,
                **(head_kwargs or {}),
            )
        }
    cos = ChiefOfStaff(kernel, [Department(DEPT, intent_keywords=["bug", "fix"])])
    return WorkPump(kernel, spawner, cos, heads, executor, max_attempts=max_attempts)


# --- US-FLT-06: a filed work item completes through the org -------------------
@pytest.mark.invariant("US-FLT-06")
async def test_filed_work_item_completes_through_the_org():
    kernel = _kernel()
    await _add_script_cap(kernel)
    pump = _pump(kernel)
    item = _item("fix the login bug")
    await kernel.store.create_work_item(item)

    assert await pump.run_once(T) is True

    done = await kernel.store.get_work_item(T, item.id)
    # the status walked PENDING -> IN_FLIGHT (the claim leg, attempts=1) -> DONE
    assert done.status == WorkStatus.DONE
    assert done.attempts == 1
    assert done.lease_owner == pump.worker_id
    # the CoS routed it and the routed head owns it
    assert done.owner_member == DEPT
    # the head decomposed it and the children joined onto the parent
    assert done.result["status"] == "ok"
    assert done.result["spawned"] == 1
    assert done.result["children"][0]["agent_type"] == "script-worker"
    assert done.degraded is False
    # the children exist as child WorkItems in the tree
    children = await kernel.store.list_work_items(T, parent_id=item.id)
    assert len(children) == 1
    assert children[0].status == WorkStatus.DONE
    assert children[0].owner_member == DEPT
    # the audit trail records the steps: checkpoints + the AGENT_SPAWN row
    checkpoints = {c.step: c.status for c in await kernel.store.list_checkpoints(T, item.id)}
    assert checkpoints == {"route": "done", "execute": "done"}
    rows = await kernel.store.audit_query(T)
    assert any(r.action_type == ActionType.AGENT_SPAWN for r in rows)
    # nothing left to claim: the pump reports idle
    assert await pump.run_once(T) is False


@pytest.mark.invariant("US-FLT-06")
async def test_durable_lane_enqueues_the_same_registered_body():
    class _DurableStub(LocalDurableExecutor):
        durable = True  # exercise the enqueue lane offline (inline execution)

    kernel = _kernel()
    await _add_script_cap(kernel)
    executor = _DurableStub()
    pump = _pump(kernel, executor=executor)
    item = _item("fix the flaky test")
    await kernel.store.create_work_item(item)

    assert await pump.run_once(T) is True
    done = await kernel.store.get_work_item(T, item.id)
    assert done.status == WorkStatus.DONE
    # the body ran as the registered durable task, not a second code path
    assert any(s.name == "task:boltrig-work-item" and s.status == "ok" for s in executor.steps)


# --- US-EXE-06: capped retries, exhaustion fails, blocked work escalates ------
@pytest.mark.invariant("US-EXE-06")
async def test_transient_failure_requeues_until_the_cap_then_fails():
    class _ExplodingHead:
        name = DEPT

        async def handle(self, work_item, context, *, prefer=None, tree_id=None):
            raise RuntimeError("boom")

    kernel = _kernel()
    pump = _pump(kernel, heads={DEPT: _ExplodingHead()}, max_attempts=2)
    item = _item()
    await kernel.store.create_work_item(item)

    # attempt 1: fails, re-queued to PENDING (attempts counted on claim)
    assert await pump.run_once(T) is True
    first = await kernel.store.get_work_item(T, item.id)
    assert first.status == WorkStatus.PENDING
    assert first.attempts == 1
    # attempt 2: the cap is reached; exhaustion fails the item with the error
    assert await pump.run_once(T) is True
    final = await kernel.store.get_work_item(T, item.id)
    assert final.status == WorkStatus.FAILED
    assert final.attempts == 2
    assert final.result["error"] == "RuntimeError"
    # a FAILED item is not claimable: no infinite retry
    assert await pump.run_once(T) is False


@pytest.mark.invariant("US-EXE-06")
async def test_cap_breach_escalates_to_a_human_and_requeue_restores_it():
    kernel = _kernel()
    await _add_script_cap(kernel)
    # 3 sub-tasks against a per-step cap of 2 -> escalation, never execution
    pump = _pump(
        kernel,
        head_kwargs={"runtime": _FanoutRuntime(3), "max_children_per_step": 2},
    )
    item = _item("fix the bug")
    await kernel.store.create_work_item(item)

    assert await pump.run_once(T) is True
    parked = await kernel.store.get_work_item(T, item.id)
    assert parked.status == WorkStatus.AWAITING_HUMAN
    assert parked.result["reason"] == "max_children_per_step"
    # the HITL escalation row exists and points at the item
    pending = await kernel.store.list_pending_hitl(T)
    assert any(r.work_item_id == item.id for r in pending)
    # no over-cap children were spawned
    assert await kernel.store.list_work_items(T, parent_id=item.id) == []
    # the pump-side re-queue seam (Beat 5 wires the HITL answer to call it):
    # a human re-queue returns the item to PENDING with a fresh retry budget
    requeued = await pump.requeue(T, item.id)
    assert requeued is not None
    assert requeued.status == WorkStatus.PENDING
    assert requeued.attempts == 0


# --- US-EXE-07: the shared store CAS caps fan-out across pump instances -------
@pytest.mark.invariant("US-EXE-07")
async def test_two_pumps_over_one_store_cannot_jointly_exceed_the_fanout_cap():
    kernel = _kernel()
    await _add_script_cap(kernel)
    store = kernel.store

    root = _item("the root epic", status=WorkStatus.DONE)  # the shared tree root
    await store.create_work_item(root)
    siblings = [
        _item("fix bug one", parent_id=root.id),
        _item("fix bug two", parent_id=root.id),
    ]
    for s in siblings:
        await store.create_work_item(s)

    def make_pump():
        spawner = build_spawner(kernel)
        head = DepartmentHead(
            DEPT, [], [], 3, spawner=spawner, store=store, runtime=_FanoutRuntime(2)
        )
        cos = ChiefOfStaff(kernel, [Department(DEPT, intent_keywords=["bug", "fix"])])
        return WorkPump(kernel, spawner, cos, {DEPT: head}, None)

    # two independent pump instances over the SAME store, budget 3, steps of 2:
    # only one step fits; the store CAS refuses the joint over-spend
    await asyncio.gather(make_pump().run_once(T), make_pump().run_once(T))

    results = [await store.get_work_item(T, s.id) for s in siblings]
    done = [i for i in results if i.status == WorkStatus.DONE]
    parked = [i for i in results if i.status == WorkStatus.AWAITING_HUMAN]
    assert len(done) == 1 and len(parked) == 1
    assert parked[0].result["reason"] == "spawn_budget_exhausted"
    # the joint spawn total never exceeded the cap of 3
    spawned = [
        i for i in await store.list_work_items(T)
        if i.parent_id in {s.id for s in siblings}
    ]
    assert len(spawned) == 2


# --- US-FLT-07: a child spawn crash is captured, never raised past the join ---
@pytest.mark.invariant("US-FLT-07")
async def test_child_spawn_failure_is_captured_not_raised_and_parent_terminates():
    kernel = _kernel()

    class _ExplodingSpawner:
        """A spawner whose spawn always raises - the D8 join must absorb it."""

        _kernel = kernel

        async def spawn(self, *args, **kwargs):
            raise RuntimeError("spawn blew up")

    # no runtime -> the deterministic decomposition yields one child sub-task
    head = DepartmentHead(DEPT, [], [], 32, spawner=_ExplodingSpawner(), store=kernel.store)
    pump = _pump(kernel, heads={DEPT: head})
    item = _item("fix the login bug")
    await kernel.store.create_work_item(item)

    # the join swallows the child crash: run_once completes, no exception escapes
    assert await pump.run_once(T) is True

    done = await kernel.store.get_work_item(T, item.id)
    # the parent reached a terminal state, carrying the degradation honestly
    assert done.status == WorkStatus.DONE
    assert done.degraded is True
    child = done.result["children"][0]
    assert child["status"] == "error"
    assert child["degraded"] is True
    assert child["summary"].startswith("child failed")
    # the child WorkItem in the tree is recorded FAILED + degraded (US-FLT-06 tree)
    kids = await kernel.store.list_work_items(T, parent_id=item.id)
    assert len(kids) == 1
    assert kids[0].status == WorkStatus.FAILED
    assert kids[0].degraded is True


# --- US-FLT-07(b): a degraded convergent aggregate is never DONE (D6) ---------
@pytest.mark.invariant("US-FLT-07")
async def test_convergent_degraded_aggregate_parks_for_a_human_never_done():
    kernel = _kernel()
    # hermes with no endpoint: every child degrades instead of reasoning (P9)
    await kernel.store.upsert_capability(
        AgentCapability("hermes-worker", T, "hermes", ["*"], 3, True, "standard")
    )
    pump = _pump(kernel)

    convergent = _item("fix the bug", convergent=True)
    await kernel.store.create_work_item(convergent)
    assert await pump.run_once(T) is True
    parked = await kernel.store.get_work_item(T, convergent.id)
    assert parked.status == WorkStatus.AWAITING_HUMAN  # never DONE (D6)
    assert parked.degraded is True
    pending = await kernel.store.list_pending_hitl(T)
    assert any(r.work_item_id == convergent.id for r in pending)

    # the non-convergent twin completes DONE with degraded=true carried
    divergent = _item("fix the other bug", convergent=False)
    await kernel.store.create_work_item(divergent)
    assert await pump.run_once(T) is True
    done = await kernel.store.get_work_item(T, divergent.id)
    assert done.status == WorkStatus.DONE
    assert done.degraded is True


# --- D7: the chat fast lane files its follow-ons into the org lane ------------
@pytest.mark.invariant("US-FLT-07")
async def test_chat_turn_persists_new_work_items_and_stamps_degraded():
    kernel = _kernel()

    class _StubSpawner:
        async def spawn(self, tenant_id, task, skills, prefer, context, *,
                        partial_on_budget=True, grant_ceiling=None):
            return {
                "summary": "did it",
                "degraded": True,
                "new_work_items": ["file the follow-up report"],
            }

    chat = ChatService(
        kernel.store, EventRelay(),
        turn_executor=build_turn_executor(kernel, _StubSpawner(), continuity=False),
    )
    _ = [e async for e in chat.handle_turn(
        tenant_id=T, user_id="alice", role="engineer", message="do the thing"
    )]

    items = await kernel.store.list_work_items(T)
    turn = next(i for i in items if i.parent_id is None)
    # the degraded flag from the spawn result persists on the turn's item
    assert turn.degraded is True
    assert turn.status == WorkStatus.DONE
    # the follow-on became a PENDING child for the org lane, owner unset
    child = next(i for i in items if i.parent_id == turn.id)
    assert child.status == WorkStatus.PENDING
    assert child.source == "chat"
    assert child.owner_member is None
    assert child.on_behalf_of == "alice"
    assert "follow-up" in child.intent


# --- the org factory: manifest hierarchy in, minimal default out (P9) ---------
async def test_build_org_reads_the_manifest_hierarchy():
    from boltrig.config.manifest import FleetManifest, HierarchyConfig, HierarchyTier

    kernel = _kernel()
    manifest = FleetManifest(
        organisation=T, tenant_id=T,
        hierarchy=HierarchyConfig(
            tier1=HierarchyTier(name="chief-of-staff"),
            tier2=(
                HierarchyTier(
                    name="head-of-engineering", department="engineering",
                    supported_skills=("analysis/*", "integration/refactor"),
                ),
                HierarchyTier(name="head-of-sales", department="sales"),
            ),
        ),
    )
    pump = build_org(kernel, build_spawner(kernel), manifest)
    assert sorted(pump.heads) == ["engineering", "sales"]
    # wildcard patterns describe capabilities, not loadable skill ids
    assert pump.heads["engineering"].domain_skills == ["integration/refactor"]


async def test_build_org_without_hierarchy_degrades_to_the_default_org():
    kernel = _kernel()
    await _add_script_cap(kernel)
    pump = build_org(kernel, build_spawner(kernel), None)  # no manifest at all
    assert list(pump.heads) == ["general"]
    item = _item("do a general thing")
    await kernel.store.create_work_item(item)
    assert await pump.run_once(T) is True
    done = await kernel.store.get_work_item(T, item.id)
    assert done.status == WorkStatus.DONE
    assert done.owner_member == "general"
