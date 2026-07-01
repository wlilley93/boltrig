"""Live Hatchet integration (Beat 5; P1-1 lineage).

Gated on a reachable Hatchet engine (HATCHET_CLIENT_TOKEN set); skipped offline so
the default suite stays green (P9). It proves the live execution path of the
registered durable tasks: ``boltrig-invoke`` runs on the real engine and its body
re-enters the kernel chokepoint (FR-EXE-06); ``boltrig-workflow-run`` is accepted
as a durable task and pauses on a HITL-gated step instead of completing
(NFR-REL-01/NFR-REL-03 live half). The checkpoint-resume and exactly-once
properties are proven deterministically offline in test_durable_resume.py; the
full live pause -> approve -> resume loop over a shared Postgres store is the
Beat 6 live gate.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not os.environ.get("HATCHET_CLIENT_TOKEN"),
    reason="set HATCHET_CLIENT_TOKEN (+ a reachable Hatchet engine) for the live test",
)

# The worker boots from the repo manifest (manifest.example.yaml, tenant acme).
_TENANT = "acme"


def _envelope(run_id: str) -> dict:
    from boltrig.fleet.hatchet_app import context_to_envelope
    from boltrig.models import GrantSet, InvocationContext

    return context_to_envelope(
        InvocationContext(
            tenant_id=_TENANT, run_id=run_id, grants=GrantSet.of(["*"]),
            actor="live-test", actor_tier="human",
        )
    )


def _start_worker() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "boltrig.fleet.hatchet_worker"],
        cwd=str(_REPO),
        env=dict(os.environ),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


async def test_live_invoke_reenters_the_chokepoint():
    """boltrig-invoke runs on the real engine: a pure-data payload, the body
    rebuilds the context and dispatches through kernel.invoke (FR-EXE-06)."""
    from boltrig.fleet.hatchet_app import TASK_INVOKE, InvokeInput, build_hatchet_app

    hatchet, workflows = build_hatchet_app()
    worker = _start_worker()
    try:
        await asyncio.sleep(9)  # let the worker register with the engine
        rid = uuid.uuid4().hex
        result = await asyncio.wait_for(
            workflows[TASK_INVOKE].aio_run(
                InvokeInput(
                    tenant=_TENANT, noun="skill", verb="skill.search",
                    params={"query": "anything"}, ctx_envelope=_envelope(rid),
                    run_id=rid,
                )
            ),
            timeout=45,
        )
        # the task returns the chokepoint's Result data (tolerate a name wrap)
        out = result
        if isinstance(out, dict) and "skills" not in out:
            out = next((v for v in out.values() if isinstance(v, dict)), out)
        assert isinstance(out, dict) and "skills" in out, result
    finally:
        if worker.poll() is None:
            worker.kill()


async def test_live_workflow_run_pauses_on_gated_step():
    """A durable boltrig-workflow-run whose step hits the HITL gate pauses (does
    not complete) - the durable wait registered by the engine is what a scoped
    approval event resumes (NFR-REL-01). Needs DATABASE_URL so the test and the
    worker share one store for the workflow definition."""
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("set DATABASE_URL (shared store) for the live pause test")
    from boltrig.fleet.hatchet_app import (
        TASK_WORKFLOW_RUN,
        WorkflowRunInput,
        build_hatchet_app,
    )
    from boltrig.models import WorkflowDefinition, WorkflowSource
    from boltrig.store import PostgresStore

    store = await PostgresStore.connect(os.environ["DATABASE_URL"])
    wf_id = f"live-gated-{uuid.uuid4().hex[:8]}"
    await store.upsert_workflow(
        WorkflowDefinition(
            id=wf_id, tenant_id=_TENANT, version="1", source=WorkflowSource.PRECREATED,
            # channel.send is consequence=high: the gate holds it (SEC-14)
            definition={"steps": [{"id": "s1", "action": "channel.send",
                                   "params": {"channel_id": "none", "text": "x"}}]},
        )
    )
    hatchet, workflows = build_hatchet_app()
    worker = _start_worker()
    try:
        await asyncio.sleep(9)
        rid = uuid.uuid4().hex
        ref = await workflows[TASK_WORKFLOW_RUN].aio_run_no_wait(
            WorkflowRunInput(
                tenant=_TENANT, workflow_id=wf_id, inputs={},
                ctx_envelope=_envelope(rid), run_id=rid,
            )
        )
        # it must NOT complete on its own within a short window (it is paused
        # on the durable approval wait)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(ref.aio_result(), timeout=12)
    finally:
        if worker.poll() is None:
            worker.kill()
