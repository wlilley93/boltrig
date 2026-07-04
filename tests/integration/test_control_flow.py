"""Control-plane step handling for the workflow interpreter (design brief sec 22).

The interpreter now recognises control nouns (trigger/flow/code) and resolves
them locally instead of failing on an unbound action. The load-bearing addition
is real conditional execution: a ``flow.branch`` step evaluates a declarative
predicate against parent outputs and records a branch label; descendant steps
that declare a matching ``branch`` run, the rest skip.

These cover the design-brief canvas node kinds that previously had no execution
semantics: Start (trigger.start), End (flow.end), Conditional (flow.branch),
Loop (flow.loop), Code (code.run). The capability node kinds (agent-call,
http, database, notify, tool) keep dispatching through kernel.invoke as before.
"""

from __future__ import annotations

import pytest

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.fleet.workers import LocalDurableExecutor
from boltrig.kernel import Kernel
from boltrig.models import (
    GrantSet,
    InvocationContext,
    TenantPermissions,
    WorkflowDefinition,
    WorkflowSource,
    WorkItem,
    WorkStatus,
)
from boltrig.store import InMemoryStore
from boltrig.workflows import WorkflowLibrary

T = "acme"


def _work(intent: str) -> WorkItem:
    return WorkItem(id=intent, tenant_id=T, source="chat", intent=intent,
                    confidence=1.0, convergent=False, status=WorkStatus.PENDING)


async def _kernel() -> Kernel:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    await k.register_adapter(T, build_tickets())
    return k


def _ctx() -> InvocationContext:
    return InvocationContext(tenant_id=T, grants=GrantSet.of(["*"]), actor="u", run_id="run-cf")


def _wf(steps: list[dict]) -> WorkflowDefinition:
    return WorkflowDefinition(
        id="wf-cf", tenant_id=T, version="1.0.0", source=WorkflowSource.PRECREATED,
        definition={"name": "cf", "version": "1", "steps": steps}, intent_tags=[],
    )


@pytest.mark.invariant("FR-CTL-03")
async def test_trigger_and_end_are_no_ops_that_complete():
    k = await _kernel()
    lib = WorkflowLibrary(k.store, executor=LocalDurableExecutor(), kernel=k)
    wf = _wf([
        {"id": "start", "parents": [], "action": "trigger.start", "params": {}},
        {"id": "work", "parents": ["start"], "action": "ticket.create", "params": {"title": "x"}},
        {"id": "end", "parents": ["work"], "action": "flow.end", "params": {}},
    ])
    await lib.register(wf)
    record = await lib.execute(T, wf.id, {"hello": "world"}, _ctx())
    by_id = {s["id"]: s for s in record["steps"]}
    assert record["status"] == "completed"
    assert by_id["start"]["status"] == "ok"
    assert by_id["start"]["output"]["entry"] is True
    assert by_id["start"]["output"]["inputs"] == {"hello": "world"}
    assert by_id["end"]["status"] == "ok"
    assert by_id["end"]["output"]["terminal"] is True


@pytest.mark.invariant("FR-CTL-03")
async def test_branch_runs_only_the_matching_arm():
    k = await _kernel()
    lib = WorkflowLibrary(k.store, executor=LocalDurableExecutor(), kernel=k)
    # A gate step sets a value, the branch reads it, only the "true" arm runs.
    wf = _wf([
        {"id": "gate", "parents": [], "action": "ticket.create",
         "params": {"title": "gate"}},
        {"id": "cond", "parents": ["gate"], "action": "flow.branch",
         "params": {"left": "$gate.output.title", "op": "eq", "right": "gate"}},
        {"id": "yes", "parents": ["cond"], "branch": "true",
         "action": "ticket.create", "params": {"title": "yes-arm"}},
        {"id": "no", "parents": ["cond"], "branch": "false",
         "action": "ticket.create", "params": {"title": "no-arm"}},
    ])
    await lib.register(wf)
    record = await lib.execute(T, wf.id, {}, _ctx())
    by_id = {s["id"]: s for s in record["steps"]}
    assert by_id["cond"]["output"]["branch"] == "true"
    assert by_id["yes"]["status"] == "ok"
    assert by_id["no"]["status"] == "skipped"
    assert by_id["no"]["reason"] == "branch_mismatch"
    assert record["status"] == "completed"


@pytest.mark.invariant("FR-CTL-03")
async def test_branch_false_arm_runs_when_predicate_is_false():
    k = await _kernel()
    lib = WorkflowLibrary(k.store, executor=LocalDurableExecutor(), kernel=k)
    wf = _wf([
        {"id": "cond", "parents": [], "action": "flow.branch",
         "params": {"left": "$missing.output.x", "op": "eq", "right": "high"}},
        {"id": "yes", "parents": ["cond"], "branch": "true",
         "action": "ticket.create", "params": {"title": "y"}},
        {"id": "no", "parents": ["cond"], "branch": "false",
         "action": "ticket.create", "params": {"title": "n"}},
    ])
    await lib.register(wf)
    record = await lib.execute(T, wf.id, {}, _ctx())
    by_id = {s["id"]: s for s in record["steps"]}
    # missing ref resolves to None != "high" -> branch false -> no arm runs
    assert by_id["cond"]["output"]["branch"] == "false"
    assert by_id["no"]["status"] == "ok"
    assert by_id["yes"]["status"] == "skipped"


@pytest.mark.invariant("FR-CTL-03")
async def test_loop_records_item_count_without_crashing():
    k = await _kernel()
    lib = WorkflowLibrary(k.store, executor=LocalDurableExecutor(), kernel=k)
    wf = _wf([
        {"id": "loop", "parents": [], "action": "flow.loop",
         "params": {"items": ["a", "b", "c"]}},
        {"id": "after", "parents": ["loop"], "action": "ticket.create",
         "params": {"title": "after-loop"}},
    ])
    await lib.register(wf)
    record = await lib.execute(T, wf.id, {}, _ctx())
    by_id = {s["id"]: s for s in record["steps"]}
    assert by_id["loop"]["status"] == "ok"
    assert by_id["loop"]["output"]["count"] == 3
    assert by_id["after"]["status"] == "ok"
    assert record["status"] == "completed"


@pytest.mark.invariant("FR-CTL-03")
async def test_code_run_is_recognised_but_not_executed():
    k = await _kernel()
    lib = WorkflowLibrary(k.store, executor=LocalDurableExecutor(), kernel=k)
    wf = _wf([
        {"id": "script", "parents": [], "action": "code.run",
         "params": {"script": "print('hi')"}},
    ])
    await lib.register(wf)
    record = await lib.execute(T, wf.id, {}, _ctx())
    by_id = {s["id"]: s for s in record["steps"]}
    assert by_id["script"]["status"] == "ok"
    assert by_id["script"]["output"]["executed"] is False
    assert "no sandbox" in by_id["script"]["output"]["reason"]
    assert record["status"] == "completed"
