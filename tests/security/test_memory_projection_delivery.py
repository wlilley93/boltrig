from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from boltrig.memory.engine import EngineFact
from boltrig.memory.projection_queue import QueuedMemoryProjectionFanout
from boltrig.memory.projections import ProjectionResult
from boltrig.models import InvocationContext, MemoryProjectionStatus
from boltrig.observability.memory_projection_delivery import (
    MAX_MEMORY_PROJECTION_RECEIPTS,
    memory_projection_delivery_fields,
    project_memory_projection_receipt,
)
from boltrig.store import InMemoryStore

TENANT = "acme"


class _Projection:
    id = "private-test-projection"

    def __init__(self, *, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    async def remember(self, tenant_id, fact, context):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError(f"provider leaked {fact.content} for {context.actor}")
        return ProjectionResult.written(f"private-ref:{fact.id}")

    async def forget(self, tenant_id, *, fact_id, projection_ref, context):
        raise AssertionError("forget was not expected")


class _Queue:
    durable = True

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, dict]] = []

    async def enqueue(self, task_name, payload):
        self.calls.append((task_name, payload))
        if self.fail:
            raise RuntimeError("queue leaked projection-super-secret")
        return "queued"


class _Loader:
    def __init__(self, fanout) -> None:
        self.fanout = fanout

    def peek(self, tenant_id, noun):
        assert noun == "memory"
        return type("MemoryAdapterStub", (), {"_projections": self.fanout})()


class _Kernel:
    def __init__(self, store, fanout) -> None:
        self.store = store
        self.loader = _Loader(fanout)


def _fact() -> EngineFact:
    return EngineFact(
        id="fact-private-id",
        owner_scope="user:alice",
        kind="entity",
        content="projection-super-secret",
    )


def _context() -> InvocationContext:
    return InvocationContext(tenant_id=TENANT, actor="alice")


@pytest.mark.invariant("SEC-WRK-36")
async def test_transient_projection_retries_with_bounded_content_free_evidence():
    store = InMemoryStore()
    queue = _Queue()
    projection = _Projection(failures=2)
    fanout = QueuedMemoryProjectionFanout(
        store,
        [projection],
        executor=queue,
        max_operation_attempts=3,
    )

    pending = await fanout.remember(TENANT, _fact(), _context())
    final = await fanout.process(queue.calls[0][1])
    stored = (await store.list_memory_projection_statuses(TENANT))[0]
    receipt = project_memory_projection_receipt(stored)

    assert pending[0]["status"] == "pending"
    assert final["status"] == "written"
    assert projection.calls == 3
    assert stored.enqueue_attempts == 1
    assert stored.operation_attempts == stored.max_operation_attempts == 3
    assert stored.first_attempt_at is not None
    assert stored.last_attempt_at is not None
    assert stored.last_failure_at is not None
    assert stored.failure_code == "projection_operation_failed"
    assert stored.error is None
    assert receipt["state"] == "delivered_after_retry"
    assert "projection-super-secret" not in repr(stored)
    assert "projection-super-secret" not in repr(receipt)


@pytest.mark.invariant("SEC-WRK-36")
async def test_poison_projection_stops_at_cap_and_duplicate_delivery_is_a_noop():
    store = InMemoryStore()
    queue = _Queue()
    projection = _Projection(failures=20)
    fanout = QueuedMemoryProjectionFanout(
        store,
        [projection],
        executor=queue,
        max_operation_attempts=3,
    )

    await fanout.remember(TENANT, _fact(), _context())
    payload = queue.calls[0][1]
    first = await fanout.process(payload)
    duplicate = await fanout.process(payload)
    stored = (await store.list_memory_projection_statuses(TENANT))[0]
    receipt = project_memory_projection_receipt(stored)

    assert first["status"] == duplicate["status"] == "failed"
    assert projection.calls == 3
    assert stored.operation_attempts == 3
    assert stored.failure_code == "projection_operation_failed"
    assert receipt["state"] == "terminal_after_retry_cap"
    assert receipt["manual_retry"] == "unavailable_original_payload_not_retained"
    assert "provider leaked" not in repr(stored)
    assert "projection-super-secret" not in repr(receipt)


@pytest.mark.invariant("SEC-WRK-36")
async def test_redelivery_resumes_the_persisted_attempt_budget():
    store = InMemoryStore()
    queue = _Queue()
    projection = _Projection(failures=0)
    fanout = QueuedMemoryProjectionFanout(
        store,
        [projection],
        executor=queue,
        max_operation_attempts=3,
    )
    await fanout.remember(TENANT, _fact(), _context())
    pending = (await store.list_memory_projection_statuses(TENANT))[0]
    attempted_at = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
    await store.upsert_memory_projection_status(
        replace(
            pending,
            operation_attempts=2,
            first_attempt_at=attempted_at,
            last_attempt_at=attempted_at,
            last_failure_at=attempted_at,
            failure_code="projection_operation_failed",
        )
    )

    final = await fanout.process(queue.calls[0][1])
    stored = (await store.list_memory_projection_statuses(TENANT))[0]

    assert final["status"] == "written"
    assert projection.calls == 1
    assert stored.operation_attempts == stored.max_operation_attempts == 3
    assert stored.first_attempt_at == attempted_at


@pytest.mark.invariant("SEC-WRK-36")
async def test_ambiguous_enqueue_failure_is_not_retried():
    store = InMemoryStore()
    queue = _Queue(fail=True)
    projection = _Projection(failures=0)
    fanout = QueuedMemoryProjectionFanout(store, [projection], executor=queue)

    result = await fanout.remember(TENANT, _fact(), _context())
    stored = (await store.list_memory_projection_statuses(TENANT))[0]

    assert len(queue.calls) == 1
    assert projection.calls == 0
    assert result[0]["status"] == stored.status == "failed"
    assert stored.enqueue_attempts == 1
    assert stored.operation_attempts == 0
    assert stored.failure_code == "enqueue_failed"
    assert stored.error is None
    assert "projection-super-secret" not in repr(stored)


@pytest.mark.invariant("SEC-WRK-36")
async def test_platform_projection_is_tenant_scoped_bounded_and_redacted():
    store = InMemoryStore()
    fanout = QueuedMemoryProjectionFanout(
        store,
        [_Projection(failures=0)],
        executor=_Queue(),
    )
    now = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
    raw_values = {
        "id": "receipt-private-id",
        "projection_id": "provider-private-id",
        "fact_id": "fact-private-id",
        "target": "target-private-id",
        "projection_ref": "backend-private-ref",
        "error": "content-private-error",
    }
    for index in range(MAX_MEMORY_PROJECTION_RECEIPTS + 2):
        await store.upsert_memory_projection_status(
            MemoryProjectionStatus(
                id=f"{raw_values['id']}-{index}",
                tenant_id=TENANT,
                projection_id=raw_values["projection_id"],
                operation="remember",
                status="failed",
                fact_id=raw_values["fact_id"],
                target=raw_values["target"],
                projection_ref=raw_values["projection_ref"],
                error=raw_values["error"],
                enqueue_attempts=1,
                operation_attempts=3,
                max_operation_attempts=3,
                last_failure_at=now,
                failure_code="projection_operation_failed",
                created_at=now - timedelta(seconds=index + 1),
                updated_at=now,
            )
        )
    await store.upsert_memory_projection_status(
        MemoryProjectionStatus(
            id="other-tenant-private-id",
            tenant_id="other",
            projection_id="other-private-provider",
            operation="remember",
            status="failed",
            fact_id="other-private-fact",
        )
    )

    fields = await memory_projection_delivery_fields(
        _Kernel(store, fanout),
        TENANT,
    )
    delivery = fields["memory_projection_delivery"]
    serialised = repr(delivery)

    assert delivery["status"] == "available"
    assert delivery["proves_queue_depth"] is False
    assert delivery["proves_worker_liveness"] is False
    assert delivery["queue_posture"]["execution_mode"] == "durable_executor"
    assert len(delivery["receipts"]) == MAX_MEMORY_PROJECTION_RECEIPTS
    assert delivery["truncated"] is True
    assert delivery["manual_retry"] == "unavailable_original_payload_not_retained"
    assert delivery["receipts"][0]["receipt_identity"].startswith("mpr_")
    assert delivery["receipts"][0]["projection_identity"].startswith("mp_")
    for value in (*raw_values.values(), "other-private-fact", "other-private-provider"):
        assert value not in serialised
