"""Workflow trigger enqueues through the durable executor (P1-1, US-WFL-01).

Offline (LocalDurableExecutor) trigger records the enqueue boundary; in
production the same path runs under Hatchet (durable=True). Unknown workflows
fail closed."""

import pytest

from boltrig.fleet.workers import LocalDurableExecutor
from boltrig.store import InMemoryStore
from boltrig.workflows.generator import generate_workflow
from boltrig.workflows.library import WorkflowLibrary

T = "acme"


async def test_trigger_enqueues_through_executor():
    executor = LocalDurableExecutor()
    lib = WorkflowLibrary(InMemoryStore(), executor=executor)
    wf = generate_workflow("onboard a new hire", ["onboard"], T)
    await lib.register(wf)

    desc = await lib.trigger(T, wf.id, {"name": "alice"})
    assert desc["status"] == "queued" and desc["run_id"]
    assert desc["durable"] is False  # local fallback is not durable (Hatchet is)
    # the enqueue was recorded as a step boundary on the backbone
    assert any(s.name == f"workflow:{wf.id}" for s in executor.steps)


async def test_trigger_unknown_workflow_fails_closed():
    lib = WorkflowLibrary(InMemoryStore())
    with pytest.raises(LookupError):
        await lib.trigger(T, "does-not-exist", {})
