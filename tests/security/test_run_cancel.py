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
from boltrig.models import GrantSet, TenantPermissions, WorkItem, WorkStatus
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

    def __init__(self, name: str = "engineering", *, on_handle=None) -> None:
        self.name = name
        self.calls = 0
        self._on_handle = on_handle

    async def handle(self, item, ctx, *, tree_id=None, prefer=None):
        self.calls += 1
        if self._on_handle is not None:
            await self._on_handle()
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

    # the adapter call was NOT interrupted mid-flight (no hard kill)
    assert head.calls == 1 and completed == ["ran"]
    # cancellation takes effect only at the NEXT cooperative point; there is none
    # after this terminal execute step, so the run completes normally, not killed.
    assert (await store.get_work_item(T, "run2")).status == WorkStatus.DONE


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
