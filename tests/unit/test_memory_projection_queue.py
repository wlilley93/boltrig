from __future__ import annotations

import pytest

from boltrig.fleet.hatchet_memory import (
    TASK_MEMORY_PROJECTION,
    register_hatchet_memory_projection_task,
    register_local_memory_projection_task,
)
from boltrig.fleet.workers import LocalDurableExecutor
from boltrig.memory.engine import EngineFact
from boltrig.memory.projection_adapters import build_memory_projection_fanout
from boltrig.memory.projection_queue import QueuedMemoryProjectionFanout
from boltrig.memory.projections import ProjectionResult
from boltrig.models import InvocationContext, TenantIsolation
from boltrig.store import InMemoryStore

T = "acme"


class _Projection:
    id = "mem0"

    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.remembered = []
        self.forgotten = []

    async def remember(self, tenant_id, fact, context):
        self.remembered.append((tenant_id, fact.id, context.actor))
        if self.fail:
            raise RuntimeError("projection down")
        return ProjectionResult.written(f"mem0:{fact.id}")

    async def forget(self, tenant_id, *, fact_id, projection_ref, context):
        self.forgotten.append((tenant_id, fact_id, projection_ref, context.actor))
        return ProjectionResult.deleted(projection_ref)


class _QueueOnly:
    def __init__(self):
        self.calls = []

    async def enqueue(self, task_name, payload):
        self.calls.append((task_name, payload))
        return "queued-1"


class _Loader:
    def __init__(self, fanout):
        self._fanout = fanout

    def peek(self, tenant_id, noun):
        assert tenant_id == T
        assert noun == "memory"
        return type("MemoryAdapterStub", (), {"_projections": self._fanout})()


class _Kernel:
    def __init__(self, fanout):
        self.loader = _Loader(fanout)


class _FakeWorkflow:
    def __init__(self, fn, validator):
        self._fn = fn
        self._validator = validator

    async def aio_run(self, payload):
        model = self._validator(**payload) if isinstance(payload, dict) else payload
        return await self._fn(model, None)


class _FakeHatchet:
    def task(self, *, name, input_validator):
        def _decorator(fn):
            return _FakeWorkflow(fn, input_validator)

        return _decorator


def _ctx(actor="alice"):
    return InvocationContext(tenant_id=T, actor=actor)


def _fact(fid="f1"):
    return EngineFact(
        id=fid,
        owner_scope="user:alice",
        kind="entity",
        content="alice likes blue",
    )


async def test_queued_projection_returns_pending_then_worker_finalises():
    store = InMemoryStore()
    queue = _QueueOnly()
    projection = _Projection()
    fanout = QueuedMemoryProjectionFanout(
        store, [projection], executor=queue, task_name=TASK_MEMORY_PROJECTION
    )

    rows = await fanout.remember(T, _fact(), _ctx())

    assert rows == [{
        "projection_id": "mem0",
        "operation": "remember",
        "status": "pending",
        "fact_id": "f1",
    }]
    assert projection.remembered == []
    assert queue.calls[0][0] == TASK_MEMORY_PROJECTION

    final = await fanout.process(queue.calls[0][1])
    stored = await store.list_memory_projection_statuses(T, fact_id="f1")

    assert final["status"] == "written"
    assert final["projection_ref"] == "mem0:f1"
    assert stored[0].status == "written"
    assert projection.remembered == [(T, "f1", "alice")]


async def test_local_executor_registration_runs_projection_task_body():
    store = InMemoryStore()
    projection = _Projection()
    fanout = QueuedMemoryProjectionFanout(store, [projection])
    executor = LocalDurableExecutor()

    register_local_memory_projection_task(executor, _Kernel(fanout))
    fanout.register_executor(executor, task_name=TASK_MEMORY_PROJECTION)

    rows = await fanout.remember(T, _fact(), _ctx())
    stored = await store.list_memory_projection_statuses(T, fact_id="f1")

    assert rows[0]["status"] == "pending"
    assert stored[0].status == "written"
    assert stored[0].projection_ref == "mem0:f1"
    assert executor.steps[0].name == f"task:{TASK_MEMORY_PROJECTION}"


async def test_hatchet_registration_exposes_memory_projection_workflow():
    store = InMemoryStore()
    queue = _QueueOnly()
    projection = _Projection()
    fanout = QueuedMemoryProjectionFanout(
        store, [projection], executor=queue, task_name=TASK_MEMORY_PROJECTION
    )

    async def resources():
        return {"kernel": _Kernel(fanout)}

    workflows = register_hatchet_memory_projection_task(_FakeHatchet(), resources)
    await fanout.remember(T, _fact(), _ctx())
    out = await workflows[TASK_MEMORY_PROJECTION].aio_run(queue.calls[0][1])

    assert out["status"] == "written"
    assert out["projection_ref"] == "mem0:f1"


async def test_queued_projection_forget_preserves_projection_ref():
    store = InMemoryStore()
    queue = _QueueOnly()
    projection = _Projection()
    fanout = QueuedMemoryProjectionFanout(
        store, [projection], executor=queue, task_name=TASK_MEMORY_PROJECTION
    )

    await fanout.remember(T, _fact(), _ctx())
    await fanout.process(queue.calls.pop(0)[1])
    rows = await fanout.forget(T, ["f1"], _ctx("bob"))
    final = await fanout.process(queue.calls[0][1])

    assert rows[0]["status"] == "pending"
    assert final == {
        "projection_id": "mem0",
        "operation": "forget",
        "status": "deleted",
        "fact_id": "f1",
        "projection_ref": "mem0:f1",
    }
    assert projection.forgotten == [(T, "f1", "mem0:f1", "bob")]


async def test_projection_task_rejects_tenant_mismatch():
    queue = _QueueOnly()
    fanout = QueuedMemoryProjectionFanout(
        InMemoryStore(), [_Projection()], executor=queue, task_name=TASK_MEMORY_PROJECTION
    )
    await fanout.remember(T, _fact(), _ctx())
    payload = dict(queue.calls[0][1])
    payload["ctx_envelope"] = {**payload["ctx_envelope"], "tenant_id": "other"}

    with pytest.raises(TenantIsolation):
        await fanout.process(payload)


def test_projection_builder_selects_queued_fanout_when_configured():
    fanout = build_memory_projection_fanout(InMemoryStore(), {
        "primary_projection": "mem0",
        "fanout": {"execution": "queued"},
        "projections": [{"id": "mem0", "enabled": "true"}],
    })

    assert isinstance(fanout, QueuedMemoryProjectionFanout)
