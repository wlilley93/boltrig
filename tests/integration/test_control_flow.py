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


@pytest.mark.invariant("FR-CTL-03")
async def test_loop_iterates_body_once_per_item():
    k = await _kernel()
    lib = WorkflowLibrary(k.store, executor=LocalDurableExecutor(), kernel=k)
    # The body (make) is a real capability step; it should run once per item,
    # each with __loop_item injected into params (the title carries the item).
    wf = _wf([
        {"id": "loop", "parents": [], "action": "flow.loop",
         "params": {"items": ["alpha", "beta", "gamma"]}},
        {"id": "make", "parents": ["loop"], "action": "ticket.create",
         "params": {"title": "seed"}},
    ])
    await lib.register(wf)
    record = await lib.execute(T, wf.id, {}, _ctx())
    by_id = {s["id"]: s for s in record["steps"]}
    assert by_id["loop"]["output"]["count"] == 3
    # The body ran 3 times (3 distinct tickets), aggregated onto the original id.
    assert by_id["make"]["status"] == "ok"
    assert by_id["make"]["output"]["count"] == 3
    assert len(by_id["make"]["output"]["iterations"]) == 3
    assert record["status"] == "completed"


@pytest.mark.invariant("FR-CTL-03")
async def test_loop_with_dynamic_items_from_parent_output():
    k = await _kernel()
    lib = WorkflowLibrary(k.store, executor=LocalDurableExecutor(), kernel=k)
    # A gate step produces a list; the loop resolves it via $ref and iterates.
    wf = _wf([
        {"id": "gate", "parents": [], "action": "ticket.create",
         "params": {"title": "g"}},
        {"id": "loop", "parents": ["gate"], "action": "flow.loop",
         "params": {"items_from": "$gate.output.tags"}},
        {"id": "body", "parents": ["loop"], "action": "ticket.create",
         "params": {"title": "x"}},
    ])
    await lib.register(wf)
    # The ticket adapter does not emit tags, so items resolves to [] -> no body
    # expansion; the body runs once (the original step is kept). Completed, no crash.
    record = await lib.execute(T, wf.id, {}, _ctx())
    by_id = {s["id"]: s for s in record["steps"]}
    assert by_id["loop"]["output"]["count"] == 0
    assert by_id["body"]["status"] == "ok"
    assert record["status"] == "completed"


async def test_hitl_pause_skips_descendants_without_checkpointing():
    # A held HITL gate pauses the step. Without the checkpoint seam (the
    # WorkflowLibrary.execute path never passes a store) the walk continues -
    # and the paused step's descendants must NOT dispatch with missing parent
    # data: a pause is treated like a failure for dependency purposes.
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store, blocking_verbs={"ticket.create"})
    await k.register_adapter(T, build_tickets())
    lib = WorkflowLibrary(k.store, executor=LocalDurableExecutor(), kernel=k)
    wf = _wf([
        {"id": "gated", "parents": [], "action": "ticket.create", "params": {"title": "x"}},
        {"id": "child", "parents": ["gated"], "action": "ticket.create",
         "params": {"title": "y"}},
    ])
    await lib.register(wf)
    record = await lib.execute(T, wf.id, {}, _ctx())
    by_id = {s["id"]: s for s in record["steps"]}
    assert by_id["gated"]["status"] == "paused"
    assert by_id["child"]["status"] == "skipped"
    assert by_id["child"]["reason"] == "parent_failed"
    assert record["status"] == "paused"


@pytest.mark.invariant("FR-CTL-03")
async def test_loop_items_are_capped_and_overflow_recorded():
    k = await _kernel()
    lib = WorkflowLibrary(k.store, executor=LocalDurableExecutor(), kernel=k)
    wf = _wf([
        {"id": "loop", "parents": [], "action": "flow.loop",
         "params": {"items": [str(i) for i in range(150)]}},
        {"id": "make", "parents": ["loop"], "action": "ticket.create",
         "params": {"title": "seed"}},
    ])
    await lib.register(wf)
    record = await lib.execute(T, wf.id, {}, _ctx())
    by_id = {s["id"]: s for s in record["steps"]}
    # The cap bounds dispatches per run; the excess is recorded as skipped.
    assert by_id["loop"]["output"]["count"] == 100
    assert by_id["loop"]["output"]["skipped_overflow"] == 50
    assert by_id["make"]["output"]["count"] == 100
    assert record["status"] == "completed"


@pytest.mark.invariant("FR-CTL-03")
async def test_loop_clones_do_not_leak_loop_metadata_into_verb_params():
    # A verb whose schema forbids additional properties must still run as a
    # loop body: __loop_item/__loop_index are dispatch metadata, stripped
    # before the params hit schema validation.
    from boltrig.adapters.base import Result, VerbSpec

    class _StrictAdapter:
        id = "strict"
        version = "0.1.0"
        runtime = "script"
        source = "builtin"

        def describe(self):
            return [VerbSpec(
                "strict.echo", "strict",
                {"type": "object",
                 "properties": {"msg": {"type": "string"}},
                 "required": ["msg"], "additionalProperties": False},
                {"type": "object"}, "low", "Echo params (strict schema).")]

        async def execute(self, verb, params, credential, context):
            return Result.success({"echo": params})

    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    await k.register_adapter(T, _StrictAdapter())
    lib = WorkflowLibrary(k.store, executor=LocalDurableExecutor(), kernel=k)
    wf = _wf([
        {"id": "loop", "parents": [], "action": "flow.loop",
         "params": {"items": ["a", "b"]}},
        {"id": "echo", "parents": ["loop"], "action": "strict.echo",
         "params": {"msg": "hi"}},
    ])
    await lib.register(wf)
    record = await lib.execute(T, wf.id, {}, _ctx())
    by_id = {s["id"]: s for s in record["steps"]}
    assert by_id["echo"]["status"] == "ok"
    for iteration in by_id["echo"]["output"]["iterations"]:
        assert iteration == {"echo": {"msg": "hi"}}
    assert record["status"] == "completed"


@pytest.mark.invariant("FR-CTL-03")
async def test_loop_mixed_parent_step_is_skipped_not_run_with_null_refs():
    k = await _kernel()
    lib = WorkflowLibrary(k.store, executor=LocalDurableExecutor(), kernel=k)
    # "mixed" depends on a loop-body step AND an external step: it falls
    # outside the expanded body, so its refs to the body original could never
    # resolve. It must be skipped with a clear reason, not run with null refs.
    wf = _wf([
        {"id": "ext", "parents": [], "action": "ticket.create", "params": {"title": "e"}},
        {"id": "loop", "parents": [], "action": "flow.loop",
         "params": {"items": ["a", "b"]}},
        {"id": "body", "parents": ["loop"], "action": "ticket.create",
         "params": {"title": "x"}},
        {"id": "mixed", "parents": ["body", "ext"], "action": "ticket.create",
         "params": {"title": "m"}},
    ])
    await lib.register(wf)
    record = await lib.execute(T, wf.id, {}, _ctx())
    by_id = {s["id"]: s for s in record["steps"]}
    assert by_id["body"]["status"] == "ok"
    assert by_id["mixed"]["status"] == "skipped"
    assert by_id["mixed"]["reason"] == "mixed_loop_parent"


async def test_checkpoints_are_scoped_by_workflow_id():
    # Two runs of DIFFERENT workflows may share a run_id (it can come from
    # context.run_id): checkpoint keys are workflow-scoped so neither run
    # replays the other's step outputs.
    from boltrig.workflows.interpreter import run_workflow_definition

    k = await _kernel()

    def _scoped(wf_id: str, title: str) -> WorkflowDefinition:
        return WorkflowDefinition(
            id=wf_id, tenant_id=T, version="1.0.0", source=WorkflowSource.PRECREATED,
            definition={"name": wf_id, "version": "1", "steps": [
                {"id": "s", "parents": [], "action": "ticket.create",
                 "params": {"title": title}},
            ]}, intent_tags=[],
        )

    first = await run_workflow_definition(
        k, _scoped("wf-a", "one"), {}, _ctx(), run_id="shared", store=k.store
    )
    second = await run_workflow_definition(
        k, _scoped("wf-b", "two"), {}, _ctx(), run_id="shared", store=k.store
    )
    assert first["steps"][0]["status"] == "ok"
    assert second["steps"][0]["status"] == "ok"
    # No cross-replay: the second workflow dispatched its own step.
    assert not second["steps"][0].get("replayed")
    cps = {c.step: c.status for c in await k.store.list_checkpoints(T, "shared")}
    assert cps == {"wf-a:s": "ok", "wf-b:s": "ok"}
