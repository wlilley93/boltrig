"""Memory/PostgreSQL parity for bounded maintenance-attempt evidence."""

from __future__ import annotations

from datetime import timedelta
import os

import pytest

from boltrig.models import BACKGROUND_JOB_RECEIPTS_PER_JOB, utcnow

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
T = "acme"


async def _make_store(kind: str):
    if kind == "memory":
        from boltrig.store import InMemoryStore

        return InMemoryStore()
    from boltrig.store import PostgresStore

    store = await PostgresStore.connect(DSN)
    await store._pool.execute("TRUNCATE background_job_receipts")
    return store


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(
                not DSN,
                reason="set BOLTRIG_TEST_DATABASE_URL for Postgres parity",
            ),
        ),
    ]
)
async def store(request):
    value = await _make_store(request.param)
    yield value
    close = getattr(value, "close", None)
    if close is not None:
        await close()


@pytest.mark.store
@pytest.mark.invariant("SEC-WRK-34")
async def test_attempt_history_merges_without_leaking_failures_on_both_stores(store):
    first = utcnow()
    identity = "bjp_111111111111111111111111"
    success = await store.record_background_job_attempt(
        tenant_id=T,
        job_name="retention",
        process_instance_identity=identity,
        interval_seconds=3600,
        attempted_at=first,
        succeeded=True,
        item_count=3,
    )
    assert success.last_success_at == first
    assert success.last_failure_at is None

    failed_at = first + timedelta(hours=1)
    failed = await store.record_background_job_attempt(
        tenant_id=T,
        job_name="retention",
        process_instance_identity=identity,
        interval_seconds=3600,
        attempted_at=failed_at,
        succeeded=False,
        item_count=0,
    )
    assert failed.last_attempt_at == failed_at
    assert failed.last_success_at == first
    assert failed.last_failure_at == failed_at
    assert failed.failure_code == "sweep_failed"
    assert "host" not in repr(failed).lower()

    await store.record_background_job_attempt(
        tenant_id="other",
        job_name="retention",
        process_instance_identity="bjp_222222222222222222222222",
        interval_seconds=3600,
        attempted_at=failed_at,
        succeeded=True,
        item_count=9,
    )
    assert await store.list_background_job_receipts(T) == [failed]


@pytest.mark.store
@pytest.mark.invariant("SEC-WRK-34")
async def test_attempt_receipts_are_pruned_to_a_deterministic_hard_bound(store):
    now = utcnow()
    for index in range(BACKGROUND_JOB_RECEIPTS_PER_JOB + 3):
        await store.record_background_job_attempt(
            tenant_id=T,
            job_name="hitl_expiry",
            process_instance_identity=f"bjp_{index:024x}",
            interval_seconds=60,
            attempted_at=now + timedelta(seconds=index),
            succeeded=True,
            item_count=index,
        )

    rows = await store.list_background_job_receipts(T)
    assert len(rows) == BACKGROUND_JOB_RECEIPTS_PER_JOB
    assert [row.last_item_count for row in rows] == [6, 5, 4, 3]
    assert all(row.receipt_kind == "attempt_history_not_liveness" for row in rows)
