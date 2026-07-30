"""Memory/Postgres parity for workflow schedules and occurrence claims."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest

from boltrig.models import (
    GrantSet,
    WorkflowSchedule,
    WorkflowScheduleOccurrence,
)

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
T = "workflow-schedule-store-tenant"
DUE = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


async def _make_store(kind: str):
    if kind == "memory":
        from boltrig.store import InMemoryStore

        return InMemoryStore()
    from boltrig.store import PostgresStore

    store = await PostgresStore.connect(DSN)
    await store._pool.execute(
        "TRUNCATE workflow_schedule_occurrences,workflow_schedules "
        "RESTART IDENTITY CASCADE"
    )
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
async def schedule_store(request):
    store = await _make_store(request.param)
    yield store
    close = getattr(store, "close", None)
    if close is not None:
        await close()


@pytest.mark.store
@pytest.mark.security
@pytest.mark.invariant("FR-WFL-20")
@pytest.mark.invariant("FR-WFL-21")
@pytest.mark.invariant("SEC-08")
async def test_schedule_desire_and_occurrence_claim_match_on_both_stores(
    schedule_store,
) -> None:
    store = schedule_store
    desired = await store.upsert_workflow_schedule(
        WorkflowSchedule(
            tenant_id=T,
            workflow_id="daily",
            workspace_id="ws-1",
            cron="0 9 * * *",
            timezone="Europe/London",
            authority_subject="author",
            grant_ceiling=GrantSet.of(
                ["control.workflow.trigger"], ["control.workflow.execute"]
            ),
            next_due_at=DUE,
        )
    )
    assert desired.grant_ceiling.allow == ("control.workflow.trigger",)
    assert await store.get_workflow_schedule("other", "daily") is None
    assert [row.workflow_id for row in await store.list_workflow_schedules(T)] == [
        "daily"
    ]

    occurrence = WorkflowScheduleOccurrence(
        tenant_id=T,
        workflow_id="daily",
        scheduled_for=DUE,
        run_id="wfs_" + "a" * 64,
        status="claimed",
        lease_owner="worker-a",
        workflow_sha256="b" * 64,
        schedule_sha256="c" * 64,
    )
    claims = await asyncio.gather(
        store.claim_workflow_schedule_occurrence(
            occurrence, lease_seconds=60
        ),
        store.claim_workflow_schedule_occurrence(
            WorkflowScheduleOccurrence(
                **{**occurrence.__dict__, "lease_owner": "worker-b"}
            ),
            lease_seconds=60,
        ),
    )
    assert sum(1 for _, claimed in claims if claimed) == 1
    winner = next(row for row, claimed in claims if claimed)
    assert not await store.finish_workflow_schedule_occurrence(
        T,
        "daily",
        DUE,
        lease_owner="not-the-owner",
        status="queued",
        engine_run_id="wrong",
        reason=None,
    )
    assert await store.finish_workflow_schedule_occurrence(
        T,
        "daily",
        DUE,
        lease_owner=winner.lease_owner,
        status="queued",
        engine_run_id="engine-run",
        reason=None,
    )
    terminal, claimed = await store.claim_workflow_schedule_occurrence(
        WorkflowScheduleOccurrence(
            **{**occurrence.__dict__, "lease_owner": "worker-c"}
        ),
        lease_seconds=60,
    )
    assert not claimed
    assert terminal.status == "queued"
    assert terminal.run_id == occurrence.run_id
    assert await store.finish_workflow_schedule_outcome(
        T,
        occurrence.run_id,
        status="succeeded",
        reason=None,
    )
    settled = await store.get_workflow_schedule_occurrence(
        T, "daily", DUE
    )
    assert settled.status == "succeeded"
    assert settled.claimed_at is not None
    assert settled.enqueued_at is not None
    assert settled.outcome_at is not None

    retry_due = DUE.replace(minute=30)
    retry_occurrence, claimed = await store.claim_workflow_schedule_occurrence(
        WorkflowScheduleOccurrence(
            **{
                **occurrence.__dict__,
                "scheduled_for": retry_due,
                "run_id": "wfs_" + "d" * 64,
                "lease_owner": "worker-retry",
            }
        ),
        lease_seconds=60,
    )
    assert claimed
    assert await store.finish_workflow_schedule_occurrence(
        T,
        "daily",
        retry_due,
        lease_owner=retry_occurrence.lease_owner,
        status="failed",
        engine_run_id=None,
        reason="schedule_dispatch_failed",
    )
    assert await store.request_workflow_schedule_occurrence_retry(
        T,
        "daily",
        retry_due,
        run_id=retry_occurrence.run_id,
        workflow_sha256="wrong",
        schedule_sha256=retry_occurrence.schedule_sha256,
        max_manual_retries=3,
    ) is None
    requested = await store.request_workflow_schedule_occurrence_retry(
        T,
        "daily",
        retry_due,
        run_id=retry_occurrence.run_id,
        workflow_sha256=retry_occurrence.workflow_sha256,
        schedule_sha256=retry_occurrence.schedule_sha256,
        max_manual_retries=3,
    )
    assert requested is not None
    assert requested.status == "retryable"
    assert requested.manual_retries == 1
    assert requested.last_retry_at is not None
    listed = await store.list_workflow_schedule_occurrences(
        T, "daily", limit=2
    )
    assert [row.scheduled_for for row in listed] == [retry_due, DUE]
    assert [row.status for row in listed] == ["retryable", "succeeded"]
    assert (
        await store.get_workflow_schedule_occurrence(
            "other", "daily", DUE
        )
        is None
    )

    assert await store.advance_workflow_schedule(
        T,
        "daily",
        expected_due_at=DUE,
        next_due_at=DUE.replace(hour=13),
        last_scheduled_for=DUE,
        status="active",
        reason=None,
    )
    assert not await store.advance_workflow_schedule(
        T,
        "daily",
        expected_due_at=DUE,
        next_due_at=DUE.replace(hour=14),
        last_scheduled_for=DUE,
        status="active",
        reason=None,
    )
    await store.delete_workflow_schedule(T, "daily")
    assert await store.get_workflow_schedule(T, "daily") is None
    # Unscheduling removes desired state, not the immutable replay receipt.
    assert (
        await store.get_workflow_schedule_occurrence(T, "daily", DUE)
    ).status == "succeeded"
