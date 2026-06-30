"""Round Twelve - the live run canvas backend (FR-EVT-04).

The interpreter emits a workflow_step event per step (step_id + status) to the
run's stream, so the canvas can light the exact node as the run walks it. The
whole run is bound to one stream (rid) so step events, the steps' tool events, and
audit all cohere.
"""

from __future__ import annotations

import pytest

from nankle.adapters.builtin.memory_tickets import build as build_tickets
from nankle.fleet.workers import LocalDurableExecutor
from nankle.kernel import Kernel
from nankle.models import (
    GrantSet,
    InvocationContext,
    TenantPermissions,
    WorkflowDefinition,
    WorkflowSource,
)
from nankle.store import InMemoryStore
from nankle.workflows import WorkflowLibrary

T = "acme"


async def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    await k.register_adapter(T, build_tickets())
    return k


def _ctx() -> InvocationContext:
    return InvocationContext(tenant_id=T, grants=GrantSet.of(["*"]), actor="u")


def _wf(steps: list[dict]) -> WorkflowDefinition:
    return WorkflowDefinition(
        id="wf-12", tenant_id=T, version="1.0.0", source=WorkflowSource.PRECREATED,
        definition={"steps": steps}, intent_tags=[],
    )


@pytest.mark.invariant("FR-EVT-04")
async def test_interpreter_emits_step_events_on_the_run_stream():
    k = await _kernel()
    lib = WorkflowLibrary(k.store, executor=LocalDurableExecutor(), kernel=k)
    wf = _wf([
        {"id": "s1", "parents": [], "action": "ticket.create", "params": {"title": "a"}},
        {"id": "s2", "parents": ["s1"], "action": "ticket.create", "params": {"title": "b"}},
    ])
    await lib.register(wf)

    record = await lib.execute(T, wf.id, {}, _ctx())
    rid = record["run_id"]
    events = k.events.snapshot(rid)
    step_events = [e for e in events if e["type"] == "workflow_step"]

    # each step emitted running -> ok, keyed by step_id
    s1 = [e for e in step_events if e["step_id"] == "s1"]
    s2 = [e for e in step_events if e["step_id"] == "s2"]
    assert [e["status"] for e in s1] == ["running", "ok"]
    assert [e["status"] for e in s2] == ["running", "ok"]
    # the run is bound to one stream: the steps' own tool events are here too
    assert any(e["type"] == "tool_call" for e in events)
    assert any(e["type"] == "tool_result" for e in events)


@pytest.mark.invariant("FR-EVT-04")
async def test_skipped_descendant_emits_skipped_step_event():
    k = await _kernel()
    lib = WorkflowLibrary(k.store, executor=LocalDurableExecutor(), kernel=k)
    wf = _wf([
        {"id": "a", "parents": [], "action": "does.notexist", "params": {}},
        {"id": "b", "parents": ["a"], "action": "ticket.create", "params": {"title": "x"}},
    ])
    await lib.register(wf)

    record = await lib.execute(T, wf.id, {}, _ctx())
    events = [e for e in k.events.snapshot(record["run_id"]) if e["type"] == "workflow_step"]
    by_id = {}
    for e in events:
        by_id.setdefault(e["step_id"], []).append(e["status"])
    assert by_id["a"][-1] in {"failed", "error"}  # unbound action
    assert by_id["b"] == ["skipped"]  # descendant of a failed step never runs
