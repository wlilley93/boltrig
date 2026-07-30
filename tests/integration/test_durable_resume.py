"""Durable tasks + the HITL resume bridge (Beat 5; NFR-REL-02/03, FR-EXE-06).

Everything runs offline via the LocalDurableExecutor: the SAME task bodies the
Hatchet worker serves (hatchet_app) run inline, a crashy counting fake proves
checkpoint-resume without re-execution, the combined trigger path proves each
step runs inside its own run_step boundary WITH checkpoints (completed steps
replay with no new boundary, only the interrupted step re-executes) plus the
completed-but-uncheckpointed idempotency replay, the answer -> notifier ->
scoped-event bridge proves the exactly-once resume (the consume_if_approved
CAS), and an ungranted verb inside a task body fails closed and is audited.
"""

from __future__ import annotations

import copy
import uuid

import pytest

from boltrig.adapters.base import Result, VerbSpec
from boltrig.api.bootstrap import wire_hitl_resume
from boltrig.fleet import build_org, build_spawner
from boltrig.fleet.hatchet_app import (
    APPROVAL_EVENT_KEY,
    TASK_INVOKE,
    TASK_WORKFLOW_RUN,
    context_to_envelope,
    register_boltrig_tasks,
    run_workflow_body,
)
from boltrig.fleet.workers import LocalDurableExecutor
from boltrig.kernel import Kernel
from boltrig.models import (
    GrantMissing,
    GrantSet,
    HITLType,
    InvocationContext,
    TenantIsolation,
    TenantPermissions,
    WorkflowDefinition,
    WorkflowSource,
    WorkItem,
    WorkStatus,
)
from boltrig.store import InMemoryStore
from boltrig.workflows.snapshot import WorkflowSnapshotError, build_workflow_snapshot

T = "acme"
_OBJ = {"type": "object"}


class SpyAdapter:
    """A counting fake: three plain job verbs plus the HITL-gated danger.go.
    Verbs added to ``crash_once`` raise on their first execution only (the
    interruption a durable re-run recovers from)."""

    id = "spy"
    version = "1"
    runtime = "script"

    def __init__(self) -> None:
        self.calls: dict[str, int] = {}
        self.params: dict[str, list[dict]] = {}
        self.crash_once: set[str] = set()

    def describe(self) -> list[VerbSpec]:
        def spec(verb: str, consequence: str = "low") -> VerbSpec:
            return VerbSpec(
                verb_id=verb,
                noun_id=verb.split(".")[0],
                input_schema=_OBJ,
                output_schema=_OBJ,
                consequence=consequence,
                description=verb,
            )

        return [
            spec("job.one"),
            spec("job.two"),
            spec("job.three"),
            spec("danger.go", consequence="high"),
        ]

    async def execute(self, verb_id, params, credential, context) -> Result:
        self.calls[verb_id] = self.calls.get(verb_id, 0) + 1
        self.params.setdefault(verb_id, []).append(copy.deepcopy(params))
        if verb_id in self.crash_once:
            self.crash_once.discard(verb_id)
            raise RuntimeError("simulated crash")
        return Result.success({"verb": verb_id, "n": self.calls[verb_id]})


async def _build() -> tuple[Kernel, SpyAdapter]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    spy = SpyAdapter()
    await kernel.register_adapter(T, spy)
    return kernel, spy


def _envelope(
    run_id: str,
    grants: list[str] | None = None,
    *,
    workspace_id: str | None = None,
) -> dict:
    return context_to_envelope(
        InvocationContext(
            tenant_id=T,
            run_id=run_id,
            grants=GrantSet.of(grants or ["*"]),
            actor="workflow-runner",
            actor_tier="tier1",
            workspace_id=workspace_id,
        )
    )


def _workflow(wf_id: str, steps: list[dict]) -> WorkflowDefinition:
    return WorkflowDefinition(
        id=wf_id,
        tenant_id=T,
        version="1",
        source=WorkflowSource.PRECREATED,
        definition={"steps": steps},
    )


# --- NFR-REL-02: resume from the last checkpoint, no re-execution ---------------
@pytest.mark.invariant("NFR-REL-02")
async def test_interrupted_run_resumes_from_last_checkpoint():
    kernel, spy = await _build()
    spy.crash_once.add("job.three")  # the interruption: step 3 of 3 dies once
    workflow = _workflow(
        "wf-crash",
        [
            {"id": "s1", "action": "job.one", "params": {}},
            {"id": "s2", "action": "job.two", "params": {}, "parents": ["s1"]},
            {"id": "s3", "action": "job.three", "params": {}, "parents": ["s2"]},
        ],
    )
    await kernel.store.upsert_workflow(workflow)
    executor = LocalDurableExecutor()
    register_boltrig_tasks(executor, kernel)
    run_id = uuid.uuid4().hex
    payload = {
        "tenant": T,
        "workflow_id": "wf-crash",
        "inputs": {},
        "ctx_envelope": _envelope(run_id),
        "run_id": run_id,
        "workflow_snapshot": build_workflow_snapshot(workflow),
    }

    # run 1 through the queue seam: the registered task body executes inline;
    # steps 1-2 complete and checkpoint, step 3 crashes.
    await executor.enqueue(TASK_WORKFLOW_RUN, dict(payload))
    assert spy.calls == {"job.one": 1, "job.two": 1, "job.three": 1}
    cps = {c.step: c.status for c in await kernel.store.list_checkpoints(T, run_id)}
    assert cps == {"wf-crash:s1": "ok", "wf-crash:s2": "ok"}  # the crash left s3 uncheckpointed

    # run 2 (the durable engine's re-run): steps 1-2 REPLAY from their
    # checkpoints - the counting spy proves they were not re-dispatched - and
    # the run completes.
    record = await run_workflow_body(kernel, dict(payload))
    assert record["status"] == "completed"
    assert spy.calls == {"job.one": 1, "job.two": 1, "job.three": 2}
    by_id = {s["id"]: s for s in record["steps"]}
    assert by_id["s1"].get("replayed") is True
    assert by_id["s2"].get("replayed") is True
    assert by_id["s3"]["status"] == "ok" and "replayed" not in by_id["s3"]


# --- the combined path: per-step boundaries AND checkpoint-resume --------------
@pytest.mark.invariant("NFR-REL-02")
async def test_trigger_path_combines_step_boundaries_and_checkpoint_resume():
    """The trigger/engine path wires BOTH durability seams: each step
    dispatches inside its own executor.run_step boundary AND checkpoints.
    A resume replays completed steps (no re-dispatch, no new boundary) and
    re-executes only the step that died."""
    kernel, spy = await _build()
    spy.crash_once.add("job.three")  # the interruption: step 3 of 3 dies once
    workflow = _workflow(
        "wf-combined",
        [
            {"id": "s1", "action": "job.one", "params": {}},
            {"id": "s2", "action": "job.two", "params": {}, "parents": ["s1"]},
            {"id": "s3", "action": "job.three", "params": {}, "parents": ["s2"]},
        ],
    )
    await kernel.store.upsert_workflow(workflow)
    executor = LocalDurableExecutor()
    register_boltrig_tasks(executor, kernel)
    run_id = uuid.uuid4().hex
    payload = {
        "tenant": T,
        "workflow_id": "wf-combined",
        "inputs": {},
        "ctx_envelope": _envelope(run_id),
        "run_id": run_id,
        "workflow_snapshot": build_workflow_snapshot(workflow),
    }

    # run 1 through the queue seam (the trigger path): the task body runs each
    # step inside its own recorded run_step boundary - not one opaque task.
    await executor.enqueue(TASK_WORKFLOW_RUN, dict(payload))
    boundaries = [s.name for s in executor.steps]
    assert f"task:{TASK_WORKFLOW_RUN}" in boundaries  # the engine's task unit
    for step_id in ("s1", "s2", "s3"):
        assert f"workflow:wf-combined:{step_id}" in boundaries
    assert spy.calls == {"job.one": 1, "job.two": 1, "job.three": 1}

    # run 2 (the engine's re-run) with the same combined wiring: steps 1-2
    # REPLAY from checkpoints - no re-dispatch and NO new boundary records -
    # and only the interrupted step re-executes inside a fresh boundary.
    steps_before = len(executor.steps)
    record = await run_workflow_body(kernel, dict(payload), executor=executor)
    assert record["status"] == "completed"
    assert spy.calls == {"job.one": 1, "job.two": 1, "job.three": 2}
    new_boundaries = [s.name for s in executor.steps[steps_before:]]
    assert new_boundaries == ["workflow:wf-combined:s3"]
    by_id = {s["id"]: s for s in record["steps"]}
    assert by_id["s1"].get("replayed") is True
    assert by_id["s2"].get("replayed") is True
    assert by_id["s3"]["status"] == "ok" and "replayed" not in by_id["s3"]


class _DropOnceCheckpointStore(InMemoryStore):
    """Drops ONE checkpoint write for a named step: the worker died after the
    step's verb completed but before its checkpoint landed."""

    def __init__(self) -> None:
        super().__init__()
        self.drop_step: str | None = None

    async def upsert_checkpoint(
        self, tenant_id, run_id, step, status, output=None, hitl_request_id=None
    ):
        if self.drop_step == step:
            self.drop_step = None
            raise RuntimeError("worker died before the checkpoint write")
        return await super().upsert_checkpoint(
            tenant_id, run_id, step, status, output, hitl_request_id
        )


@pytest.mark.invariant("NFR-REL-02")
async def test_completed_step_with_lost_checkpoint_replays_via_idempotency():
    """The completed-but-uncheckpointed crash window: the step's verb executed
    (completing its kernel idempotency record) but the checkpoint write was
    lost. The resumed run re-dispatches the step and the idempotency layer
    REPLAYS the recorded result - the verb's side effects never run twice."""
    store = _DropOnceCheckpointStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    spy = SpyAdapter()
    await kernel.register_adapter(T, spy)
    workflow = _workflow("wf-lost-ck", [{"id": "s1", "action": "job.one", "params": {}}])
    await store.upsert_workflow(workflow)
    executor = LocalDurableExecutor()
    register_boltrig_tasks(executor, kernel)
    run_id = uuid.uuid4().hex
    payload = {
        "tenant": T,
        "workflow_id": "wf-lost-ck",
        "inputs": {},
        "ctx_envelope": _envelope(run_id),
        "run_id": run_id,
        "workflow_snapshot": build_workflow_snapshot(workflow),
    }
    store.drop_step = "wf-lost-ck:s1"

    # run 1 "dies": the verb executed but the checkpoint write was lost. The
    # interpreter's P9 guard records the step as errored instead of crashing
    # the fleet; either way the run is interrupted with s1 uncheckpointed.
    first = await run_workflow_body(kernel, dict(payload), executor=executor)
    assert first["status"] == "failed"
    assert {s["id"]: s for s in first["steps"]}["s1"]["status"] == "error"
    assert spy.calls == {"job.one": 1}
    assert await store.list_checkpoints(T, run_id) == []

    # run 2: no checkpoint, so the step re-dispatches - but the idempotency
    # layer replays the recorded result, so the verb never re-executes.
    record = await run_workflow_body(kernel, dict(payload), executor=executor)
    assert record["status"] == "completed"
    assert spy.calls == {"job.one": 1}  # no double side effects
    cps = {c.step: c.status for c in await store.list_checkpoints(T, run_id)}
    assert cps == {"wf-lost-ck:s1": "ok"}  # the checkpoint lands on the re-run


@pytest.mark.invariant("NFR-REL-03")
async def test_combined_path_hitl_pause_resume_stays_exactly_once():
    """A HITL pause/resume through the COMBINED path (executor boundary +
    checkpoints + per-step idempotency key) stays exactly-once: the gate held
    the verb, the resumed run re-invokes with the approval id, and a duplicate
    resume is a pure checkpoint replay."""
    kernel, spy = await _build()
    workflow = _workflow(
        "wf-gated-combined",
        [{"id": "g1", "action": "danger.go", "params": {}}],
    )
    await kernel.store.upsert_workflow(workflow)
    executor = LocalDurableExecutor()
    register_boltrig_tasks(executor, kernel)
    wire_hitl_resume(kernel, executor=executor)
    run_id = "run-gated-combined"
    payload = {
        "tenant": T,
        "workflow_id": "wf-gated-combined",
        "inputs": {},
        "ctx_envelope": _envelope(run_id),
        "run_id": run_id,
        "workflow_snapshot": build_workflow_snapshot(workflow),
    }

    # the gated step pauses inside its own run_step boundary; the gate held
    # the verb (SEC-14), nothing executed, and the idempotency claim was
    # released with the pause so the resume can re-claim it.
    first = await run_workflow_body(kernel, dict(payload), executor=executor)
    assert first["status"] == "paused"
    assert spy.calls.get("danger.go") is None
    assert any(s.name == "workflow:wf-gated-combined:g1" for s in executor.steps)
    req = (await kernel.hitl.list_pending(T))[0]
    await kernel.hitl.answer(T, req.id, "approve", "will@acme")

    # deliver the resume TWICE through the combined path: the CAS lets exactly
    # one execution through; the second delivery is a pure checkpoint replay.
    second = await run_workflow_body(kernel, dict(payload), executor=executor)
    assert second["status"] == "completed"
    third = await run_workflow_body(kernel, dict(payload), executor=executor)
    assert third["status"] == "completed"
    assert spy.calls == {"danger.go": 1}
    assert {s["id"]: s for s in third["steps"]}["g1"].get("replayed") is True


@pytest.mark.invariant("FR-WFL-19")
async def test_loop_replay_uses_stable_iteration_checkpoints():
    kernel, spy = await _build()
    workflow = _workflow(
        "wf-loop-replay",
        [
            {
                "id": "loop",
                "action": "flow.loop",
                "params": {"items": [{"value": "a"}, {"value": "b"}]},
            },
            {
                "id": "body",
                "action": "job.one",
                "parents": ["loop"],
                "params": {"payload": None, "position": None},
                "loop_bindings": {"payload": "item", "position": "index"},
            },
        ],
    )
    await kernel.store.upsert_workflow(workflow)
    run_id = "run-loop-replay"
    payload = {
        "tenant": T,
        "workflow_id": workflow.id,
        "inputs": {},
        "ctx_envelope": _envelope(run_id),
        "run_id": run_id,
        "workflow_snapshot": build_workflow_snapshot(workflow),
    }
    executor = LocalDurableExecutor()

    first = await run_workflow_body(kernel, dict(payload), executor=executor)
    second = await run_workflow_body(kernel, dict(payload), executor=executor)

    assert first["status"] == second["status"] == "completed"
    assert spy.calls == {"job.one": 2}
    assert spy.params["job.one"] == [
        {"payload": {"value": "a"}, "position": 0},
        {"payload": {"value": "b"}, "position": 1},
    ]
    by_id = {step["id"]: step for step in second["steps"]}
    assert by_id["loop"]["replayed"] is True
    assert by_id["body"]["output"]["count"] == 2
    assert [step.name for step in executor.steps] == [
        "workflow:wf-loop-replay:body__0",
        "workflow:wf-loop-replay:body__1",
    ]
    checkpoints = {
        checkpoint.step: checkpoint.status
        for checkpoint in await kernel.store.list_checkpoints(T, run_id)
    }
    assert checkpoints == {
        "wf-loop-replay:loop": "ok",
        "wf-loop-replay:body__0": "ok",
        "wf-loop-replay:body__1": "ok",
    }


@pytest.mark.invariant("FR-WFL-19")
async def test_loop_hitl_approves_each_bound_iteration_exactly_once():
    kernel, spy = await _build()
    workflow = _workflow(
        "wf-loop-hitl",
        [
            {
                "id": "loop",
                "action": "flow.loop",
                "params": {"items": ["first", "second"]},
            },
            {
                "id": "body",
                "action": "danger.go",
                "parents": ["loop"],
                "params": {"value": None, "position": None},
                "loop_bindings": {"value": "item", "position": "index"},
            },
        ],
    )
    await kernel.store.upsert_workflow(workflow)
    run_id = "run-loop-hitl"
    payload = {
        "tenant": T,
        "workflow_id": workflow.id,
        "inputs": {},
        "ctx_envelope": _envelope(run_id),
        "run_id": run_id,
        "workflow_snapshot": build_workflow_snapshot(workflow),
    }

    first = await run_workflow_body(kernel, dict(payload))
    assert first["status"] == "paused"
    assert spy.calls == {}
    first_request = (await kernel.hitl.list_pending(T))[0]
    await kernel.hitl.answer(T, first_request.id, "approve", "will@acme")

    second = await run_workflow_body(kernel, dict(payload))
    assert second["status"] == "paused"
    assert spy.calls == {"danger.go": 1}
    second_request = (await kernel.hitl.list_pending(T))[0]
    assert second_request.id != first_request.id
    await kernel.hitl.answer(T, second_request.id, "approve", "will@acme")

    third = await run_workflow_body(kernel, dict(payload))
    fourth = await run_workflow_body(kernel, dict(payload))

    assert third["status"] == fourth["status"] == "completed"
    assert spy.calls == {"danger.go": 2}
    assert spy.params["danger.go"] == [
        {"value": "first", "position": 0},
        {"value": "second", "position": 1},
    ]
    checkpoints = {
        checkpoint.step: checkpoint.status
        for checkpoint in await kernel.store.list_checkpoints(T, run_id)
        if checkpoint.step.startswith("wf-loop-hitl:")
    }
    assert checkpoints == {
        "wf-loop-hitl:loop": "ok",
        "wf-loop-hitl:body__0": "ok",
        "wf-loop-hitl:body__1": "ok",
    }


@pytest.mark.invariant("SEC-138")
async def test_queued_workflow_executes_the_approved_snapshot_not_latest_definition():
    kernel, spy = await _build()
    original = _workflow("wf-snapshot", [{"id": "approved", "action": "job.one", "params": {}}])
    await kernel.store.upsert_workflow(original)
    payload = {
        "tenant": T,
        "workflow_id": original.id,
        "workflow_snapshot": build_workflow_snapshot(original),
        "inputs": {},
        "ctx_envelope": _envelope("run-snapshot"),
        "run_id": "run-snapshot",
    }
    await kernel.store.upsert_workflow(
        _workflow("wf-snapshot", [{"id": "changed", "action": "job.two", "params": {}}])
    )

    record = await run_workflow_body(kernel, payload)

    assert record["status"] == "completed"
    assert spy.calls == {"job.one": 1}


@pytest.mark.invariant("SEC-138")
async def test_workflow_snapshot_rejects_tampering_and_cross_workspace_replay():
    kernel, _ = await _build()
    workflow = _workflow("wf-scoped", [{"id": "approved", "action": "job.one", "params": {}}])
    workflow.workspace_id = "workspace-a"
    snapshot = build_workflow_snapshot(workflow)
    payload = {
        "tenant": T,
        "workflow_id": workflow.id,
        "workflow_snapshot": snapshot,
        "inputs": {},
        "ctx_envelope": _envelope("run-scoped", workspace_id="workspace-b"),
        "run_id": "run-scoped",
    }
    with pytest.raises(WorkflowSnapshotError, match="outside the active workspace"):
        await run_workflow_body(kernel, payload)

    tampered = copy.deepcopy(payload)
    tampered["ctx_envelope"] = _envelope("run-scoped", workspace_id="workspace-a")
    tampered["workflow_snapshot"]["workflow"]["definition"] = {"steps": []}
    with pytest.raises(WorkflowSnapshotError, match="digest mismatch"):
        await run_workflow_body(kernel, tampered)


# --- NFR-REL-03: a HITL answer resumes the paused run exactly once --------------
@pytest.mark.invariant("NFR-REL-03")
async def test_hitl_answer_resumes_paused_run_exactly_once():
    kernel, spy = await _build()
    workflow = _workflow(
        "wf-gated",
        [
            {"id": "g1", "action": "danger.go", "params": {}},
        ],
    )
    await kernel.store.upsert_workflow(workflow)
    executor = LocalDurableExecutor()
    register_boltrig_tasks(executor, kernel)
    wire_hitl_resume(kernel, executor=executor)
    run_id = "run-gated"
    payload = {
        "tenant": T,
        "workflow_id": "wf-gated",
        "inputs": {},
        "ctx_envelope": _envelope(run_id),
        "run_id": run_id,
        "workflow_snapshot": build_workflow_snapshot(workflow),
    }

    # the gated step pauses; the gate held the verb (SEC-14), nothing executed
    first = await run_workflow_body(kernel, dict(payload))
    assert first["status"] == "paused"
    assert spy.calls.get("danger.go") is None
    cps = {c.step: c for c in await kernel.store.list_checkpoints(T, run_id)}
    assert cps["wf-gated:g1"].status == "paused" and cps["wf-gated:g1"].hitl_request_id
    req = (await kernel.hitl.list_pending(T))[0]
    assert req.id == cps["wf-gated:g1"].hitl_request_id

    # answer() fires the notifier: the scoped approval event reached the bus
    await kernel.hitl.answer(T, req.id, "approve", "will@acme")
    events = [e for e in executor.events if e["key"] == APPROVAL_EVENT_KEY]
    assert events and events[0]["scope"] == run_id
    assert events[0]["payload"]["hitl_request_id"] == req.id
    assert events[0]["payload"]["decision"] == "approve"

    # deliver the resume TWICE: the consume_if_approved CAS lets exactly one
    # execution through; the second delivery is a pure checkpoint replay.
    second = await run_workflow_body(kernel, dict(payload))
    assert second["status"] == "completed"
    third = await run_workflow_body(kernel, dict(payload))
    assert third["status"] == "completed"
    assert spy.calls == {"danger.go": 1}
    assert {s["id"]: s for s in third["steps"]}["g1"].get("replayed") is True


@pytest.mark.invariant("NFR-REL-03")
async def test_hitl_answer_requeues_the_parked_work_item():
    # The pump-side half of the bridge: answering a request tied to a parked
    # (AWAITING_HUMAN) work item requeues it to PENDING with a fresh budget.
    kernel, _ = await _build()
    pump = build_org(kernel, build_spawner(kernel))
    wire_hitl_resume(kernel, pump=pump)
    item = WorkItem(
        id=uuid.uuid4().hex,
        tenant_id=T,
        source="internal",
        intent="parked work",
        confidence=0.9,
        convergent=False,
        status=WorkStatus.AWAITING_HUMAN,
        attempts=3,
    )
    await kernel.store.create_work_item(item)
    req = await kernel.hitl.create(
        tenant_id=T,
        run_id=item.id,
        type=HITLType.ESCALATION,
        question="needs a human",
        work_item_id=item.id,
    )
    await kernel.hitl.answer(T, req.id, "approve", "will@acme")
    requeued = await kernel.store.get_work_item(T, item.id)
    assert requeued.status == WorkStatus.PENDING
    assert requeued.attempts == 0  # intervention restores the retry budget


async def test_resume_notifier_failure_never_breaks_the_answer():
    # P9: the bridge is fail-safe - a raising notifier never voids the answer.
    kernel, _ = await _build()

    def _boom(_req):
        raise RuntimeError("boom")

    kernel.hitl.set_resume_notifier(_boom)
    req = await kernel.hitl.create(
        tenant_id=T,
        run_id="r",
        type=HITLType.APPROVAL,
        question="q",
        verb="danger.go",
        requested_by="workflow-runner",
        request_fingerprint="danger-fingerprint",
    )
    resp = await kernel.hitl.answer(T, req.id, "approve", "will@acme")
    assert resp.decision == "approve"
    assert (
        await kernel.hitl.consume_if_approved(T, req.id, "danger.go", "danger-fingerprint") is True
    )


# --- FR-EXE-06: governance is not bypassable from inside a durable task ---------
@pytest.mark.invariant("FR-EXE-06")
async def test_task_body_cannot_bypass_governance():
    kernel, spy = await _build()
    executor = LocalDurableExecutor()
    register_boltrig_tasks(executor, kernel)
    run_id = "run-denied"
    # the envelope grants job.one only; the task asks for job.two
    with pytest.raises(GrantMissing):
        await executor.enqueue(
            TASK_INVOKE,
            {
                "tenant": T,
                "noun": "job",
                "verb": "job.two",
                "params": {},
                "ctx_envelope": _envelope(run_id, grants=["job.one"]),
                "run_id": run_id,
            },
        )
    assert spy.calls.get("job.two") is None  # fail-closed: never executed
    rows = await kernel.store.audit_query(T)
    denied = [r for r in rows if r.verb == "job.two" and r.status == "grant_missing"]
    assert denied and denied[0].run_id == run_id  # the denial is audited (SEC-16)


@pytest.mark.invariant("FR-EXE-06")
async def test_task_payload_tenant_must_match_the_envelope():
    # a payload naming one tenant with an envelope for another is refused
    # before any dispatch (SEC-08, K-22)
    kernel, spy = await _build()
    executor = LocalDurableExecutor()
    register_boltrig_tasks(executor, kernel)
    with pytest.raises(TenantIsolation):
        await executor.enqueue(
            TASK_INVOKE,
            {
                "tenant": "other-tenant",
                "noun": "job",
                "verb": "job.one",
                "params": {},
                "ctx_envelope": _envelope("run-x"),
                "run_id": "run-x",
            },
        )
    assert spy.calls == {}
