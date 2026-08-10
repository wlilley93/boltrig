"""Live Hatchet integration (Beat 5 + Beat 6; P1-1 lineage).

Gated on a reachable Hatchet engine (HATCHET_CLIENT_TOKEN set); skipped offline so
the default suite stays green (P9). It proves the live execution path of the
registered durable tasks: ``boltrig-invoke`` runs on the real engine and its body
re-enters the kernel chokepoint (FR-EXE-06); ``boltrig-workflow-run`` is accepted
as a durable task and pauses on a HITL-gated step instead of completing
(NFR-REL-01/NFR-REL-03 live half). The checkpoint-resume and exactly-once
properties are proven deterministically offline in test_durable_resume.py;
``test_live_kill_restart_approve_resume`` is the Beat 6 crown-jewel live gate:
a worker crash (SIGKILL) mid-pause, an approval recorded over the shared
Postgres store, and a fresh worker completing the run with checkpoint replay
(NFR-REL-02) and exactly-once gated execution (NFR-REL-03).

Live timing note: engine dispatch to a fresh worker can take 45-75s (worse just
after an engine restart, or while dead "ghost" workers linger with unexpired
liveness and burn a task timeout first). All live waits are therefore generous
(>= 150s) and store-driven (poll checkpoints), never single fixed sleeps.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not os.environ.get("HATCHET_CLIENT_TOKEN"),
    reason="set HATCHET_CLIENT_TOKEN (+ a reachable Hatchet engine) for the live test",
)

def _shared_db_url() -> str | None:
    """The shared-store URL for the live legs.

    tests/conftest strips ``DATABASE_URL`` for hermeticity (a test must not
    inherit product behaviour from the shell); the SANCTIONED kept variable is
    ``BOLTRIG_TEST_DATABASE_URL``. Accept it first; keep the bare name as a
    fallback for running this file outside the repo conftest.
    """
    return os.environ.get("BOLTRIG_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")



def _worker_tenant() -> str:
    """The tenant the worker will seed: derived exactly as the worker derives
    it (first manifest found wins; a box-local manifest.yaml outranks the repo
    example), so the test never assumes a tenant the worker did not seed."""
    from boltrig.api.bootstrap import _find_manifest
    from boltrig.config import load_manifest

    path = _find_manifest()
    if path:
        try:
            return load_manifest(path).tenant_id
        except Exception:
            pass
    return "default"


_TENANT = _worker_tenant()


def _envelope(run_id: str) -> dict:
    from boltrig.fleet.hatchet_app import context_to_envelope
    from boltrig.models import GrantSet, InvocationContext

    return context_to_envelope(
        InvocationContext(
            tenant_id=_TENANT,
            run_id=run_id,
            grants=GrantSet.of(["*"]),
            actor="live-test",
            actor_tier="human",
        )
    )


def _start_worker() -> subprocess.Popen:
    # Own process group (start_new_session): the hatchet SDK spawns listener
    # child processes, and killing only the parent leaves them heartbeating as
    # ghost "active" workers that swallow every subsequent dispatch.
    # tests/conftest strips product env (DATABASE_URL, HATCHET_* except the
    # kept token) for hermeticity; the spawned worker is PRODUCT, not test, so
    # re-inject what its bootstrap needs from the sanctioned kept variables.
    env = dict(os.environ)
    db = _shared_db_url()
    if db:
        env["DATABASE_URL"] = db
    env.setdefault("HATCHET_CLIENT_TLS_STRATEGY", "none")
    return subprocess.Popen(
        [sys.executable, "-m", "boltrig.fleet.hatchet_worker"],
        cwd=str(_REPO),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _kill_worker(worker: subprocess.Popen) -> None:
    """SIGKILL the worker's WHOLE process group - honest crash semantics (a dead
    box takes its children with it) and no ghost listeners left behind."""
    try:
        os.killpg(worker.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        if worker.poll() is None:
            worker.kill()
    worker.wait()


async def _poll_checkpoints(store, run_id: str, ready, *, budget: float, interval: float = 2.0):
    """Poll the shared store's checkpoints for ``run_id`` until ``ready(by_step)``
    accepts them, returning the by-step dict. Store-driven polling (not fixed
    sleeps) because live engine dispatch to a fresh worker can take 45-75s."""
    deadline = time.monotonic() + budget
    by_step: dict = {}

    def _step_key(step: str) -> str | None:
        # Interpreter checkpoint keys are workflow-scoped ("<wf_id>:<step>");
        # the kernel's held-call bookkeeping uses the reserved "held:" prefix
        # (kernel/held_call.py) and is not a workflow step. Normalize to bare
        # step ids so the predicates below read as authored.
        if step.startswith("held:"):
            return None
        return step.split(":", 1)[1] if ":" in step else step

    while time.monotonic() < deadline:
        by_step = {}
        for c in await store.list_checkpoints(_TENANT, run_id):
            key = _step_key(c.step)
            if key is not None:
                by_step[key] = c
        if ready(by_step):
            return by_step
        await asyncio.sleep(interval)
    state = {s: c.status for s, c in by_step.items()}
    raise AssertionError(f"checkpoints not ready within {budget}s: {state}")


async def test_live_invoke_reenters_the_chokepoint():
    """boltrig-invoke runs on the real engine: a pure-data payload, the body
    rebuilds the context and dispatches through kernel.invoke (FR-EXE-06)."""
    from boltrig.fleet.hatchet_app import TASK_INVOKE, InvokeInput, build_hatchet_app

    hatchet, workflows = build_hatchet_app()
    worker = _start_worker()
    try:
        await asyncio.sleep(9)  # let the worker register with the engine
        rid = uuid.uuid4().hex
        # generous window: engine dispatch to a fresh worker can take 45-75s
        # (worse after an engine restart / with lingering ghost workers).
        result = await asyncio.wait_for(
            workflows[TASK_INVOKE].aio_run(
                InvokeInput(
                    tenant=_TENANT,
                    noun="skill",
                    verb="skill.search",
                    params={"query": "anything"},
                    ctx_envelope=_envelope(rid),
                    run_id=rid,
                )
            ),
            timeout=180,
        )
        # the task returns the chokepoint's Result data (tolerate a name wrap)
        out = result
        if isinstance(out, dict) and "skills" not in out:
            out = next((v for v in out.values() if isinstance(v, dict)), out)
        assert isinstance(out, dict) and "skills" in out, result
    finally:
        _kill_worker(worker)


async def test_live_workflow_run_pauses_on_gated_step():
    """A durable boltrig-workflow-run whose step hits the HITL gate pauses (does
    not complete) - the durable wait registered by the engine is what a scoped
    approval event resumes (NFR-REL-01). Needs DATABASE_URL so the test and the
    worker share one store for the workflow definition."""
    if not _shared_db_url():
        pytest.skip("set BOLTRIG_TEST_DATABASE_URL (shared store) for the live pause test")
    from boltrig.fleet.hatchet_app import (
        TASK_WORKFLOW_RUN,
        WorkflowRunInput,
        build_hatchet_app,
    )
    from boltrig.models import WorkflowDefinition, WorkflowSource
    from boltrig.store import PostgresStore

    store = await PostgresStore.connect(_shared_db_url())
    wf_id = f"live-gated-{uuid.uuid4().hex[:8]}"
    workflow = WorkflowDefinition(
        id=wf_id,
        tenant_id=_TENANT,
        version="1",
        source=WorkflowSource.PRECREATED,
        # channel.send is consequence=high: the gate holds it (SEC-14)
        definition={
            "steps": [
                {
                    "id": "s1",
                    "action": "channel.send",
                    "params": {"channel_id": "none", "text": "x"},
                }
            ]
        },
    )
    await store.upsert_workflow(workflow)
    from boltrig.workflows.snapshot import build_workflow_snapshot

    hatchet, workflows = build_hatchet_app()
    worker = _start_worker()
    try:
        await asyncio.sleep(9)
        rid = uuid.uuid4().hex
        ref = await workflows[TASK_WORKFLOW_RUN].aio_run_no_wait(
            WorkflowRunInput(
                tenant=_TENANT,
                workflow_id=wf_id,
                workflow_snapshot=build_workflow_snapshot(workflow),
                inputs={},
                ctx_envelope=_envelope(rid),
                run_id=rid,
            )
        )
        # Poll the shared store until the gated step's PAUSED checkpoint lands
        # (dispatch latency can be 45-75s, so a fixed short timeout is flaky).
        by_step = await _poll_checkpoints(
            store,
            rid,
            lambda c: c.get("s1") is not None and c["s1"].status == "paused",
            budget=150,
        )
        assert by_step["s1"].hitl_request_id  # the pause carries its approval id
        # and the run must NOT complete on its own: it is parked on the durable
        # approval wait (NFR-REL-01), so the result stays unresolved.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(ref.aio_result(), timeout=5)
    finally:
        _kill_worker(worker)


@pytest.mark.invariant("FR-WFL-17")
async def test_live_ultracode_run_fans_out_agent_child_tasks():
    """Live v2 gate: Ultracode parent dispatches child phase-agent tasks."""
    if not _shared_db_url():
        pytest.skip("set BOLTRIG_TEST_DATABASE_URL (shared store) for the live Ultracode test")
    from boltrig.fleet.hatchet_app import TASK_ULTRACODE_RUN, build_hatchet_app
    from boltrig.fleet.hatchet_ultracode import UltracodeRunInput
    from boltrig.models import ActionType, AgentCapability, GrantSet, TenantPermissions
    from boltrig.store import PostgresStore

    store = await PostgresStore.connect(_shared_db_url())
    capability = f"live-script-{uuid.uuid4().hex[:8]}"
    seed = store.set_tenant_permissions(TenantPermissions(_TENANT, GrantSet.of(["*"])))
    if hasattr(seed, "__await__"):
        await seed
    await store.upsert_capability(
        AgentCapability(capability, _TENANT, "python-script", ["*"], 2, True, "cheap")
    )
    hatchet, workflows = build_hatchet_app()
    worker = _start_worker()
    try:
        await asyncio.sleep(9)
        rid = uuid.uuid4().hex
        workflow = {
            "workflow_name": "live-ultracode",
            "defaults": {"capability": capability, "max_total_agents": 2},
            "phases": [
                {
                    "id": "phase-01",
                    "concurrency": 2,
                    "agents": [
                        {"id": "map", "prompt": "Map the repo."},
                        {"id": "risk", "prompt": "Find risks."},
                    ],
                }
            ],
        }
        result = await asyncio.wait_for(
            workflows[TASK_ULTRACODE_RUN].aio_run(
                UltracodeRunInput(
                    tenant=_TENANT,
                    workflow=workflow,
                    ctx_envelope=_envelope(rid),
                    run_id=rid,
                    goal="prove live Ultracode fanout",
                )
            ),
            timeout=240,
        )
        record = (
            result
            if "status" in result
            else next(
                (v for v in result.values() if isinstance(v, dict) and "status" in v),
                {},
            )
        )
        assert record["status"] == "completed"
        by_step = await _poll_checkpoints(
            store,
            rid,
            lambda c: (
                {
                    "ultracode:phase-01:map",
                    "ultracode:phase-01:risk",
                    "ultracode:phase-01",
                }
                <= set(c)
                and all(cp.status == "completed" for cp in c.values())
            ),
            budget=150,
        )
        phase = by_step["ultracode:phase-01"].output
        assert phase["status"] == "completed"
        assert {a["result"]["agent_type"] for a in phase["agents"]} == {capability}
        assert {a["result"]["output"]["runtime"] for a in phase["agents"]} == {"python-script"}
        events = await store.audit_query(_TENANT, limit=1000)
        spawns = [
            e
            for e in events
            if e.parent_run_id == rid
            and e.action_type == ActionType.AGENT_SPAWN
            and e.detail.get("capability") == capability
        ]
        assert len(spawns) == 2
        assert {e.actor for e in spawns} == {capability}
    finally:
        _kill_worker(worker)


@pytest.mark.invariant("NFR-REL-02")
@pytest.mark.invariant("NFR-REL-03")
async def test_live_kill_restart_approve_resume():
    """The Beat 6 crown jewel, live: a durable run survives a worker CRASH.

    s1 (skill.search) completes and is checkpointed; s2 (channel.send,
    consequence=high) pauses on the HITL gate; worker A is SIGKILLed mid-pause;
    the approval is recorded over the SHARED Postgres store and the scoped
    resume event pushed; worker B (a fresh process) receives the engine's
    re-dispatch and completes the run. Proven live: s1 REPLAYS from its
    checkpoint, never re-executes (NFR-REL-02); s2 executes exactly once via
    the consume-if-approved CAS (NFR-REL-03, SEC-14); s3 runs to completion."""
    if not _shared_db_url():
        pytest.skip("set BOLTRIG_TEST_DATABASE_URL (shared store) for the live kill/restart test")
    from boltrig.fleet.hatchet_app import (
        TASK_WORKFLOW_RUN,
        WorkflowRunInput,
        approve,
        build_hatchet_app,
    )
    from boltrig.kernel.hitl import HITLManager
    from boltrig.models import Channel, WorkflowDefinition, WorkflowSource
    from boltrig.store import PostgresStore

    store = await PostgresStore.connect(_shared_db_url())
    # A real enabled channel (no outbound_url) so the approved send SUCCEEDS:
    # delivery is honestly "queued" for the sidecar and the Result is success,
    # letting the run finish instead of failing on an unknown channel.
    ch_id = f"live-ch-{uuid.uuid4().hex[:8]}"
    await store.upsert_channel(
        Channel(
            id=ch_id,
            tenant_id=_TENANT,
            platform="webhook",
            name="live kill/restart",
            transport="webhook",
        )
    )
    wf_id = f"live-crash-{uuid.uuid4().hex[:8]}"
    workflow = WorkflowDefinition(
        id=wf_id,
        tenant_id=_TENANT,
        version="1",
        source=WorkflowSource.PRECREATED,
        definition={
            "steps": [
                {"id": "s1", "action": "skill.search", "params": {"query": "s1"}},
                # consequence=high: the gate holds it until approved (SEC-14)
                {
                    "id": "s2",
                    "action": "channel.send",
                    "params": {"channel_id": ch_id, "text": "x"},
                    "parents": ["s1"],
                },
                {
                    "id": "s3",
                    "action": "skill.search",
                    "params": {"query": "s3"},
                    "parents": ["s2"],
                },
            ]
        },
    )
    await store.upsert_workflow(workflow)
    from boltrig.workflows.snapshot import build_workflow_snapshot

    hatchet, workflows = build_hatchet_app()
    rid = uuid.uuid4().hex
    worker_a = _start_worker()
    worker_b: subprocess.Popen | None = None
    extra_workers: list[subprocess.Popen] = []
    try:
        await asyncio.sleep(9)  # let worker A register with the engine
        ref = await workflows[TASK_WORKFLOW_RUN].aio_run_no_wait(
            WorkflowRunInput(
                tenant=_TENANT,
                workflow_id=wf_id,
                workflow_snapshot=build_workflow_snapshot(workflow),
                inputs={},
                ctx_envelope=_envelope(rid),
                run_id=rid,
            )
        )
        # Phase 1: s1 done, s2 paused with its approval id (dispatch can take
        # 45-75s on this engine, so the budget is generous).
        by_step = await _poll_checkpoints(
            store,
            rid,
            lambda c: (
                c.get("s1") is not None
                and c["s1"].status == "ok"
                and c.get("s2") is not None
                and c["s2"].status == "paused"
                and bool(c["s2"].hitl_request_id)
            ),
            budget=180,
        )
        s1_stamp = by_step["s1"].updated_at
        hitl_id = by_step["s2"].hitl_request_id

        # Phase 2: CRASH worker A (SIGKILL to the whole group, no graceful drain).
        _kill_worker(worker_a)

        # Phase 3: approve over the shared store. The answer is recorded FIRST
        # so consume_if_approved finds it, THEN the scoped resume event is
        # pushed (the same order wire_hitl_resume uses, NFR-REL-03). The
        # HITLManager over the shared store is exactly what the kernel wires
        # (Kernel.__init__: HITLManager(store)).
        await HITLManager(store).answer(_TENANT, hitl_id, "approve", respondent="live-test")
        await approve(hatchet, rid)

        # Phase 4: a FRESH worker picks up the engine's re-dispatch and the
        # interpreter resumes from checkpoints to completion. Because the crash
        # window briefly leaves ZERO registered workers, the engine parks the
        # re-dispatch as REQUEUED_NO_WORKER, and (observed on this engine) the
        # rescue reassignment fires on a fresh worker REGISTRATION and only for
        # requeues older than about two minutes. So poll in slices and, between
        # slices, scale up another worker - the ops-realistic nudge - until the
        # run completes or the overall budget runs out.
        worker_b = _start_worker()
        done = lambda c: c.get("s3") is not None and c["s3"].status == "ok"  # noqa: E731
        deadline = time.monotonic() + 480
        while True:
            try:
                by_step = await _poll_checkpoints(
                    store,
                    rid,
                    done,
                    budget=max(5.0, min(90.0, deadline - time.monotonic())),
                )
                break
            except AssertionError:
                if time.monotonic() >= deadline:
                    raise
                extra_workers.append(_start_worker())  # registration nudge
        assert by_step["s2"].status == "ok"
        # NFR-REL-02: s1 replayed from its checkpoint on the resumed run - the
        # interpreter never re-dispatched it, so its row was never rewritten.
        assert by_step["s1"].updated_at == s1_stamp
        # NFR-REL-03: the gated verb executed exactly once (the CAS), and the
        # replayed s1 added no second skill.search execution (2 = s1 + s3).
        events = await store.audit_query(_TENANT, run_id=rid, limit=500)
        sends_ok = [e for e in events if e.verb == "channel.send" and e.status == "ok"]
        assert len(sends_ok) == 1, [(e.verb, e.status) for e in events]
        searches_ok = [e for e in events if e.verb == "skill.search" and e.status == "ok"]
        assert len(searches_ok) == 2, [(e.verb, e.status) for e in events]
        # Best-effort SDK-side confirmation: the workflow-run result, when the
        # listener delivers it, reports completed. Checkpoints above are the
        # authoritative proof either way.
        try:
            result = await asyncio.wait_for(ref.aio_result(), timeout=30)
        except Exception:
            result = None
        if isinstance(result, dict):
            record = (
                result
                if "status" in result
                else next((v for v in result.values() if isinstance(v, dict) and "status" in v), {})
            )
            assert record.get("status") == "completed", result
    finally:
        for w in (worker_a, worker_b, *extra_workers):
            if w is not None:
                _kill_worker(w)
