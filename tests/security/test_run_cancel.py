"""Server-side run cancellation ([2026] VJS-COUNTY 6).

A terminal ``WorkStatus.CANCELLED`` plus a cooperative, owner-only, audited cancel
signal keyed by run id. These tests pin the HOLDING and its directives:

- SEC-85 (D5): the ``POST /v1/runs/{run_id}/cancel`` route is owner-only,
  fail-closed and audited - a non-owner / scoped-read caller gets 403 with NO
  write and NO audit, an unknown run is 404 with no write, the owner's cancel
  writes the durable cancel-request row plus a keys-only ``run.cancel`` audit
  event, and ChatService.cancel ends a live chat turn's SSE stream cleanly.
- SEC-86 (D3): the pump consults the cancel signal at each step boundary and
  stops BEFORE dispatching the next verb (head.handle never runs); a cancel that
  arrives during an in-flight adapter call NEVER interrupts it.
- SEC-87 (D1/D4): CANCELLED is terminal, neutral (outcome score None), and
  durable - it is written in a finally with a checkpoint + one audit row on the
  transition, and a restart that re-detects the durable request re-cancels the
  run rather than resurrecting it.
- SEC-166 (D3): the marker is re-read at boundary 2, the cooperative point AFTER
  the completed step, so no new domain effect BEGINS after revocation - a cancel
  that lands during head.handle spawns no follow-on work items and learns no
  workflow, while the completed step's own record survives.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.fleet import WorkPump
from boltrig.fleet.chat import ChatService
from boltrig.fleet.pump import outcome_score
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.kernel.events import EventRelay
from boltrig.models import GrantSet, TenantPermissions, WorkflowSource, WorkItem, WorkStatus
from boltrig.store import InMemoryStore

T = "acme"


def _hdr(subject: str, role: str = "engineer") -> dict:
    return {"x-boltrig-tenant": T, "x-boltrig-subject": subject, "x-boltrig-role": role,
            "x-boltrig-grants": "", "x-boltrig-departments": ""}


def _stub_executor(reply: str):
    async def executor(*, run_id, relay, **kw):
        relay.publish(run_id, {"type": "text_delta", "delta": reply})

    return executor


def _item(run_id: str, owner: str = "alice", **kw) -> WorkItem:
    return WorkItem(
        id=run_id, tenant_id=T, source="internal", intent="do the thing",
        confidence=0.9, convergent=kw.pop("convergent", False),
        status=kw.pop("status", WorkStatus.IN_FLIGHT), on_behalf_of=owner, **kw,
    )


class _SpyCoS:
    def __init__(self, dept: str = "engineering", *, on_route=None) -> None:
        self.dept = dept
        self._on_route = on_route

    async def route(self, item, ctx):
        if self._on_route is not None:
            await self._on_route(item)
        return self.dept


class _SpyHead:
    """A head whose ``handle`` records that it ran (so we can prove it was, or was
    not, dispatched) and optionally fires a hook mid-call (an in-flight adapter)."""

    def __init__(self, name: str = "engineering", *, on_handle=None, outcome=None) -> None:
        self.name = name
        self.calls = 0
        self._on_handle = on_handle
        self._outcome = outcome

    async def handle(self, item, ctx, *, tree_id=None, prefer=None):
        self.calls += 1
        if self._on_handle is not None:
            await self._on_handle()
        if self._outcome is not None:
            return dict(self._outcome)
        return {"status": "done", "children": [], "spawned": 0}


def _pump(store, head, cos=None) -> WorkPump:
    # a bare-store pump: no kernel, so the audit writer is built over the store.
    return WorkPump(store, None, cos or _SpyCoS(head.name), {head.name: head})


# --- SEC-85: owner-only, fail-closed, audited route + clean stream ----------

def _client():
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    chat = ChatService(store, kernel.events, turn_executor=_stub_executor("hi"))
    client = TestClient(create_app(kernel, chat_service=chat, platform={}))
    return client, store


async def _seed_run(store, run_id: str = "runX", owner: str = "alice") -> None:
    await store.create_work_item(
        WorkItem(id=run_id, tenant_id=T, source="chat", intent="x", confidence=1.0,
                 convergent=False, status=WorkStatus.IN_FLIGHT, hatchet_run_id=run_id,
                 on_behalf_of=owner)
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-85")
@pytest.mark.invariant("SEC-25")
def test_cancel_is_owner_only_fail_closed():
    client, store = _client()
    asyncio.run(_seed_run(store, "runX", "alice"))
    url = "/v1/runs/runX/cancel"

    # a non-owner is refused 403 with NO write
    assert client.post(url, headers=_hdr("bob")).status_code == 403
    # a scoped-read role (org-admin may READ a run, SEC-25) still cannot cancel it
    assert client.post(url, headers=_hdr("carol", role="org-admin")).status_code == 403
    # nothing was written and nothing was audited on the denied attempts
    assert not asyncio.run(store.is_run_cancel_requested(T, "runX"))
    events = asyncio.run(store.audit_query(T, limit=200))
    assert not [e for e in events if e.verb == "run.cancel"]

    # the owner cancels: 200, a durable request row, and a keys-only audit event
    res = client.post(url, headers=_hdr("alice"))
    assert res.status_code == 200 and res.json()["run_id"] == "runX"
    assert asyncio.run(store.is_run_cancel_requested(T, "runX"))
    cancels = [e for e in asyncio.run(store.audit_query(T, limit=200))
               if e.verb == "run.cancel"]
    assert len(cancels) == 1 and cancels[0].detail["run_id"] == "runX"


@pytest.mark.security
@pytest.mark.invariant("SEC-85")
def test_cancel_unknown_run_is_404_no_write():
    client, store = _client()
    res = client.post("/v1/runs/ghost/cancel", headers=_hdr("alice"))
    assert res.status_code == 404
    assert not asyncio.run(store.is_run_cancel_requested(T, "ghost"))


@pytest.mark.security
@pytest.mark.invariant("SEC-85")
async def test_chat_cancel_closes_the_run_stream():
    relay = EventRelay()
    chat = ChatService(InMemoryStore(), relay, turn_executor=_stub_executor("x"))
    run_id = "runZ"
    scoped = relay.for_tenant(T)
    got: list[dict] = []

    async def consume():
        async for ev in scoped.subscribe(run_id, replay=True):
            got.append(ev)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)  # let the subscriber attach
    await chat.cancel(T, run_id)
    await asyncio.wait_for(task, timeout=1)
    # the subscriber received the cancel notice and the stream ended cleanly
    assert any(e.get("type") == "cancelled" for e in got)


# --- SEC-86: cooperative only, never mid-adapter -----------------------------

@pytest.mark.security
@pytest.mark.invariant("SEC-86")
async def test_pump_stops_before_dispatch_at_the_chokepoint_boundary():
    store = InMemoryStore()
    item = _item("run1")
    await store.create_work_item(item)
    head = _SpyHead()

    # a cancel that arrives while routing (after route, before execute) is caught
    # at the chokepoint boundary: the execute verb (head.handle) is never dispatched.
    async def cancel_during_route(it):
        await store.request_run_cancel(T, it.id, "alice")

    pump = _pump(store, head, cos=_SpyCoS(head.name, on_route=cancel_during_route))
    await pump.handle_claimed_item(item)

    assert head.calls == 0  # stopped BEFORE dispatching the next verb (D3)
    assert (await store.get_work_item(T, "run1")).status == WorkStatus.CANCELLED


@pytest.mark.security
@pytest.mark.invariant("SEC-86")
@pytest.mark.invariant("SEC-166")
async def test_in_flight_adapter_call_is_not_interrupted():
    store = InMemoryStore()
    item = _item("run2")
    await store.create_work_item(item)
    completed: list[str] = []

    async def during_handle():
        # a cancel arrives DURING the in-flight adapter call ...
        await store.request_run_cancel(T, "run2", "alice")
        completed.append("ran")  # ... which still runs to completion, uninterrupted

    head = _SpyHead(on_handle=during_handle)
    pump = _pump(store, head)
    await pump.handle_claimed_item(item)

    # the adapter call was NOT interrupted mid-flight (no hard kill): the step ran to
    # completion. D3 is about never interrupting a step, not about ignoring the cancel.
    assert head.calls == 1 and completed == ["ran"]
    # cancellation then lands at the NEXT cooperative point, which is boundary 2 - the
    # point immediately after the completed step (SEC-166). The terminal state reflects
    # the marker as REFRESHED there, never the stale pre-dispatch read.
    assert (await store.get_work_item(T, "run2")).status == WorkStatus.CANCELLED


# --- SEC-166: no new domain effect BEGINS after revocation -------------------

@pytest.mark.security
@pytest.mark.invariant("SEC-166")
async def test_a_cancel_during_the_step_spawns_no_follow_on_work():
    """The heart of it: a cancel arriving during ``head.handle`` must not let the run
    go on to CREATE fresh work items. Those items are new domain effects that the pump
    would subsequently claim and execute, so a cancelled run would keep growing a tree
    of live work. Asserted against the STORE, not against a flag."""
    store = InMemoryStore()
    item = _item("run5")
    await store.create_work_item(item)

    async def during_handle():
        await store.request_run_cancel(T, "run5", "alice")

    # the head returns follow-on work: under the stale-marker bug these were persisted
    # AFTER the cancel had already been requested.
    head = _SpyHead(on_handle=during_handle, outcome={
        "status": "done", "children": [], "spawned": 0,
        "new_work_items": [{"intent": "downstream work that must never start"}],
    })
    await _pump(store, head).handle_claimed_item(item)

    # NOTHING new was persisted: no child of this run exists to be claimed later.
    assert await store.list_work_items(T, parent_id="run5") == []
    # and the whole tenant queue is empty of anything the cancelled run could have made
    assert [i.id for i in await store.list_work_items(T)] == ["run5"]
    assert (await store.get_work_item(T, "run5")).status == WorkStatus.CANCELLED


@pytest.mark.security
@pytest.mark.invariant("SEC-166")
async def test_a_cancel_during_the_step_learns_no_workflow():
    """A cancelled run must not mutate the flywheel: promoting its workflow into the
    reusable library is a new domain effect that outlives the run itself."""
    from boltrig.workflows import generate_workflow

    store = InMemoryStore()
    item = _item("run6")
    await store.create_work_item(item)
    wf = generate_workflow("do the thing", ["engineering"], T)
    assert wf.source == WorkflowSource.GENERATED

    async def during_handle():
        await store.request_run_cancel(T, "run6", "alice")

    head = _SpyHead(on_handle=during_handle, outcome={
        "status": "done", "children": [], "spawned": 0, "generated_workflow": wf,
    })
    await _pump(store, head).handle_claimed_item(item)

    # the library was NOT mutated: nothing was promoted to LEARNED by a cancelled run
    assert await store.list_workflows(T) == []
    assert (await store.get_work_item(T, "run6")).status == WorkStatus.CANCELLED


@pytest.mark.security
@pytest.mark.invariant("SEC-166")
async def test_the_completed_steps_own_record_survives_the_cancel():
    """The invariant is "no new effect BEGINS after revocation", NOT "pretend the
    completed step never ran". The step's aggregate really happened, so it is still
    recorded on the item; only its DOWNSTREAM effects are suppressed."""
    store = InMemoryStore()
    item = _item("run7")
    await store.create_work_item(item)

    async def during_handle():
        await store.request_run_cancel(T, "run7", "alice")

    head = _SpyHead(on_handle=during_handle, outcome={
        "status": "done", "children": [{"id": "kid", "degraded": False}], "spawned": 1,
        "new_work_items": [{"intent": "must not start"}],
    })
    await _pump(store, head).handle_claimed_item(item)

    after = await store.get_work_item(T, "run7")
    assert after.status == WorkStatus.CANCELLED
    # the work that DID happen is not lost: the head's aggregate is preserved ...
    assert after.result["spawned"] == 1
    assert after.result["children"] == [{"id": "kid", "degraded": False}]
    # ... carrying the neutral cancel outcome alongside it, not a DONE score.
    assert after.result["outcome"]["score"] is None
    assert after.result["outcome"]["terminal_status"] == "cancelled"
    # but its downstream effect still never began
    assert await store.list_work_items(T, parent_id="run7") == []


@pytest.mark.security
@pytest.mark.invariant("SEC-166")
async def test_an_uncancelled_run_is_completely_unaffected():
    """The contrast case: without it every SEC-166 assertion above could pass by the
    pump simply never persisting follow-on work or learning at all."""
    from boltrig.workflows import generate_workflow

    store = InMemoryStore()
    item = _item("run8")
    await store.create_work_item(item)
    wf = generate_workflow("do the thing", ["engineering"], T)

    head = _SpyHead(outcome={  # no cancel is ever requested for this run
        "status": "done", "children": [], "spawned": 0, "generated_workflow": wf,
        "new_work_items": [{"intent": "legitimate follow-on work"}],
    })
    await _pump(store, head).handle_claimed_item(item)

    after = await store.get_work_item(T, "run8")
    assert after.status == WorkStatus.DONE
    assert after.result["outcome"]["score"] == 1.0
    # the normal path still spawns its follow-on work ...
    kids = await store.list_work_items(T, parent_id="run8")
    assert [k.intent for k in kids] == ["legitimate follow-on work"]
    assert all(k.status == WorkStatus.PENDING for k in kids)
    # ... and still turns the flywheel
    assert [w.source for w in await store.list_workflows(T)] == [WorkflowSource.LEARNED]


# --- SEC-87: terminal, neutral, durable via finally --------------------------

@pytest.mark.security
@pytest.mark.invariant("SEC-87")
async def test_cancelled_is_terminal_neutral_checkpointed_and_audited():
    store = InMemoryStore()
    item = _item("run3", workspace_id="ws-1")
    await store.create_work_item(item)
    await store.request_run_cancel(T, "run3", "alice")
    head = _SpyHead()
    pump = _pump(store, head)

    await pump.handle_claimed_item(item)
    after = await store.get_work_item(T, "run3")

    # terminal CANCELLED, and NEUTRAL - neither a success nor a failure (D1)
    assert after.status == WorkStatus.CANCELLED
    assert after.result["outcome"]["score"] is None
    assert after.result["outcome"]["terminal_status"] == "cancelled"
    # a checkpoint marks the transition (D4)
    cps = await store.list_checkpoints(T, "run3")
    assert any(c.step == "execute" and c.status == "cancelled" for c in cps)
    # exactly one audit row on the transition, keys only (D4)
    cancels = [e for e in await store.audit_query(T, limit=200) if e.verb == "work.cancel"]
    assert len(cancels) == 1
    assert cancels[0].status == "cancelled" and cancels[0].detail["work_item_id"] == "run3"
    assert cancels[0].workspace_id == "ws-1"


@pytest.mark.security
@pytest.mark.invariant("SEC-87")
def test_outcome_score_cancelled_is_neutral():
    # a cancel scores neutral (None) whether or not the item degraded - it is
    # never counted as a success or a failure (D1), mirroring AWAITING_HUMAN.
    assert outcome_score(WorkStatus.CANCELLED.value, degraded=False)["score"] is None
    assert outcome_score(WorkStatus.CANCELLED.value, degraded=True)["score"] is None
    assert outcome_score(WorkStatus.CANCELLED.value, False)["terminal_status"] == "cancelled"


@pytest.mark.security
@pytest.mark.invariant("SEC-87")
async def test_restart_does_not_resurrect_a_cancelled_run():
    store = InMemoryStore()
    item = _item("run4")
    await store.create_work_item(item)
    await store.request_run_cancel(T, "run4", "alice")
    head = _SpyHead()
    pump = _pump(store, head)

    # first pass: the run is cancelled
    await pump.handle_claimed_item(item)
    assert (await store.get_work_item(T, "run4")).status == WorkStatus.CANCELLED

    # a "restart" re-handles the same run: the durable cancel-request row is
    # re-detected, so the run is re-cancelled (idempotent), NEVER resurrected to
    # running / DONE, and the execute verb is still never dispatched.
    reclaimed = await store.get_work_item(T, "run4")
    await pump.handle_claimed_item(reclaimed)
    assert head.calls == 0
    assert (await store.get_work_item(T, "run4")).status == WorkStatus.CANCELLED
