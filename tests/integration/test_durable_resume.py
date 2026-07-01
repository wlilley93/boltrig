"""Durable tasks + the HITL resume bridge (Beat 5; NFR-REL-02/03, FR-EXE-06).

Everything runs offline via the LocalDurableExecutor: the SAME task bodies the
Hatchet worker serves (hatchet_app) run inline, a crashy counting fake proves
checkpoint-resume without re-execution, the answer -> notifier -> scoped-event
bridge proves the exactly-once resume (the consume_if_approved CAS), and an
ungranted verb inside a task body fails closed and is audited.
"""

from __future__ import annotations

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
        self.crash_once: set[str] = set()

    def describe(self) -> list[VerbSpec]:
        def spec(verb: str, consequence: str = "low") -> VerbSpec:
            return VerbSpec(
                verb_id=verb, noun_id=verb.split(".")[0], input_schema=_OBJ,
                output_schema=_OBJ, consequence=consequence, description=verb,
            )

        return [spec("job.one"), spec("job.two"), spec("job.three"),
                spec("danger.go", consequence="high")]

    async def execute(self, verb_id, params, credential, context) -> Result:
        self.calls[verb_id] = self.calls.get(verb_id, 0) + 1
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


def _envelope(run_id: str, grants: list[str] | None = None) -> dict:
    return context_to_envelope(
        InvocationContext(
            tenant_id=T, run_id=run_id, grants=GrantSet.of(grants or ["*"]),
            actor="workflow-runner", actor_tier="tier1",
        )
    )


def _workflow(wf_id: str, steps: list[dict]) -> WorkflowDefinition:
    return WorkflowDefinition(
        id=wf_id, tenant_id=T, version="1", source=WorkflowSource.PRECREATED,
        definition={"steps": steps},
    )


# --- NFR-REL-02: resume from the last checkpoint, no re-execution ---------------
@pytest.mark.invariant("NFR-REL-02")
async def test_interrupted_run_resumes_from_last_checkpoint():
    kernel, spy = await _build()
    spy.crash_once.add("job.three")  # the interruption: step 3 of 3 dies once
    await kernel.store.upsert_workflow(_workflow("wf-crash", [
        {"id": "s1", "action": "job.one", "params": {}},
        {"id": "s2", "action": "job.two", "params": {}, "parents": ["s1"]},
        {"id": "s3", "action": "job.three", "params": {}, "parents": ["s2"]},
    ]))
    executor = LocalDurableExecutor()
    register_boltrig_tasks(executor, kernel)
    run_id = uuid.uuid4().hex
    payload = {"tenant": T, "workflow_id": "wf-crash", "inputs": {},
               "ctx_envelope": _envelope(run_id), "run_id": run_id}

    # run 1 through the queue seam: the registered task body executes inline;
    # steps 1-2 complete and checkpoint, step 3 crashes.
    await executor.enqueue(TASK_WORKFLOW_RUN, dict(payload))
    assert spy.calls == {"job.one": 1, "job.two": 1, "job.three": 1}
    cps = {c.step: c.status for c in await kernel.store.list_checkpoints(T, run_id)}
    assert cps == {"s1": "ok", "s2": "ok"}  # the crash left s3 uncheckpointed

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


# --- NFR-REL-03: a HITL answer resumes the paused run exactly once --------------
@pytest.mark.invariant("NFR-REL-03")
async def test_hitl_answer_resumes_paused_run_exactly_once():
    kernel, spy = await _build()
    await kernel.store.upsert_workflow(_workflow("wf-gated", [
        {"id": "g1", "action": "danger.go", "params": {}},
    ]))
    executor = LocalDurableExecutor()
    register_boltrig_tasks(executor, kernel)
    wire_hitl_resume(kernel, executor=executor)
    run_id = "run-gated"
    payload = {"tenant": T, "workflow_id": "wf-gated", "inputs": {},
               "ctx_envelope": _envelope(run_id), "run_id": run_id}

    # the gated step pauses; the gate held the verb (SEC-14), nothing executed
    first = await run_workflow_body(kernel, dict(payload))
    assert first["status"] == "paused"
    assert spy.calls.get("danger.go") is None
    cps = {c.step: c for c in await kernel.store.list_checkpoints(T, run_id)}
    assert cps["g1"].status == "paused" and cps["g1"].hitl_request_id
    req = (await kernel.hitl.list_pending(T))[0]
    assert req.id == cps["g1"].hitl_request_id

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
        id=uuid.uuid4().hex, tenant_id=T, source="internal", intent="parked work",
        confidence=0.9, convergent=False, status=WorkStatus.AWAITING_HUMAN, attempts=3,
    )
    await kernel.store.create_work_item(item)
    req = await kernel.hitl.create(
        tenant_id=T, run_id=item.id, type=HITLType.ESCALATION,
        question="needs a human", work_item_id=item.id,
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
        tenant_id=T, run_id="r", type=HITLType.APPROVAL, question="q", verb="danger.go",
    )
    resp = await kernel.hitl.answer(T, req.id, "approve", "will@acme")
    assert resp.decision == "approve"
    assert await kernel.hitl.consume_if_approved(T, req.id, "danger.go") is True


# --- FR-EXE-06: governance is not bypassable from inside a durable task ---------
@pytest.mark.invariant("FR-EXE-06")
async def test_task_body_cannot_bypass_governance():
    kernel, spy = await _build()
    executor = LocalDurableExecutor()
    register_boltrig_tasks(executor, kernel)
    run_id = "run-denied"
    # the envelope grants job.one only; the task asks for job.two
    with pytest.raises(GrantMissing):
        await executor.enqueue(TASK_INVOKE, {
            "tenant": T, "noun": "job", "verb": "job.two", "params": {},
            "ctx_envelope": _envelope(run_id, grants=["job.one"]), "run_id": run_id,
        })
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
        await executor.enqueue(TASK_INVOKE, {
            "tenant": "other-tenant", "noun": "job", "verb": "job.one", "params": {},
            "ctx_envelope": _envelope("run-x"), "run_id": "run-x",
        })
    assert spy.calls == {}
