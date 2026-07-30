"""Safe schedule occurrence receipts, exact recovery, and outcome settlement."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from boltrig.fleet.hatchet_app import context_to_envelope, run_workflow_body
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    GrantSet,
    InvocationContext,
    TenantPermissions,
    User,
    WorkflowDefinition,
    WorkflowSchedule,
    WorkflowScheduleOccurrence,
    WorkflowSource,
)
from boltrig.store import InMemoryStore
from boltrig.workflows.scheduler import (
    reconcile_workflow_schedules,
    scheduled_run_id,
    workflow_schedule_digest,
)
from boltrig.workflows.snapshot import (
    build_workflow_snapshot,
    workflow_snapshot_digest,
)

T = "workflow-occurrence-lifecycle"
AUTHOR = "workflow-author"
DUE = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
HEADERS = {
    "x-boltrig-tenant": T,
    "x-boltrig-subject": AUTHOR,
    "x-boltrig-role": "org-admin",
}


async def _setup() -> tuple[Kernel, InMemoryStore, WorkflowDefinition]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    await store.upsert_user(
        User(
            id=AUTHOR,
            tenant_id=T,
            role="org-admin",
            scope={"all": True},
        )
    )
    workflow = WorkflowDefinition(
        id="daily",
        tenant_id=T,
        version="1",
        source=WorkflowSource.PRECREATED,
        definition={"steps": []},
    )
    await store.upsert_workflow(workflow)
    schedule = WorkflowSchedule(
        tenant_id=T,
        workflow_id=workflow.id,
        workspace_id=None,
        cron="0 9 * * *",
        timezone="UTC",
        authority_subject=AUTHOR,
        grant_ceiling=GrantSet.of(["*"]),
        next_due_at=DUE + timedelta(days=2),
    )
    await store.upsert_workflow_schedule(schedule)
    return Kernel(store), store, workflow


async def _terminal_failed(
    store: InMemoryStore,
    workflow: WorkflowDefinition,
    *,
    due: datetime = DUE,
) -> WorkflowScheduleOccurrence:
    schedule = await store.get_workflow_schedule(T, workflow.id)
    assert schedule is not None
    occurrence, claimed = await store.claim_workflow_schedule_occurrence(
        WorkflowScheduleOccurrence(
            tenant_id=T,
            workflow_id=workflow.id,
            scheduled_for=due,
            run_id=scheduled_run_id(T, workflow.id, due),
            status="claimed",
            lease_owner="scheduler-a",
            workflow_sha256=workflow_snapshot_digest(workflow),
            schedule_sha256=workflow_schedule_digest(schedule),
        ),
        lease_seconds=60,
    )
    assert claimed
    assert await store.finish_workflow_schedule_occurrence(
        T,
        workflow.id,
        due,
        lease_owner=occurrence.lease_owner,
        status="failed",
        engine_run_id=None,
        reason="private backend message that must not leave the store",
    )
    failed = await store.get_workflow_schedule_occurrence(T, workflow.id, due)
    assert failed is not None
    return failed


@pytest.mark.security
@pytest.mark.invariant("FR-WFL-21")
def test_receipts_are_author_scoped_bounded_and_metadata_only() -> None:
    kernel, store, workflow = asyncio.run(_setup())
    failed = asyncio.run(_terminal_failed(store, workflow))
    client = TestClient(create_app(kernel))

    member = client.get(
        "/v1/workflows/daily/schedule/occurrences",
        headers={**HEADERS, "x-boltrig-role": "member"},
    )
    assert member.status_code == 403
    response = client.get(
        "/v1/workflows/daily/schedule/occurrences?limit=500",
        headers=HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["truncated"] is False
    assert body["backfill"] == {
        "status": "unavailable",
        "reason": "historical_backfill_not_supported_by_canonical_claim",
    }
    receipt = body["occurrences"][0]
    assert set(receipt) == {
        "scheduled_for",
        "run_id",
        "status",
        "claimed_at",
        "enqueued_at",
        "outcome_at",
        "engine_outcome",
        "reason",
        "retry",
    }
    assert receipt["run_id"] == failed.run_id
    assert receipt["status"] == "failed"
    assert receipt["reason"] == "workflow_occurrence_failed"
    assert receipt["engine_outcome"] == {
        "status": "settled",
        "recovery": "not_applicable",
    }
    assert set(receipt["retry"]) == {
        "attempts",
        "manual_retries",
        "last_retry_at",
    }
    serialized = response.text
    for private in (
        "private backend message",
        "workflow_sha256",
        "schedule_sha256",
        "grant_allow",
        "lease_owner",
        "engine_run_id",
        AUTHOR,
    ):
        assert private not in serialized


@pytest.mark.security
@pytest.mark.invariant("FR-WFL-21")
def test_pending_approval_replays_only_the_exact_failed_occurrence() -> None:
    kernel, store, workflow = asyncio.run(_setup())
    failed = asyncio.run(_terminal_failed(store, workflow))
    client = TestClient(create_app(kernel))
    timestamp = quote(failed.scheduled_for.isoformat(), safe="")
    path = f"/v1/workflows/daily/schedule/occurrences/{timestamp}/retry"
    body = {"run_id": failed.run_id}

    held = client.post(path, headers=HEADERS, json=body)
    assert held.status_code == 202
    approval_id = held.json()["hitl_request_id"]
    assert client.get(
        f"/v1/invoke/approvals/{approval_id}", headers=HEADERS
    ).json() == {"status": "pending"}
    asyncio.run(
        kernel.hitl.answer(T, approval_id, "approve", "independent-reviewer")
    )
    approved = client.post(
        path,
        headers=HEADERS,
        json={**body, "approval_id": approval_id},
    )
    assert approved.status_code == 200
    assert approved.json() == {
        "status": "ok",
        "workflow_id": "daily",
        "scheduled_for": failed.scheduled_for.isoformat(),
        "run_id": failed.run_id,
        "occurrence_status": "retryable",
        "manual_retries": 1,
    }
    retried = asyncio.run(
        store.get_workflow_schedule_occurrence(T, "daily", failed.scheduled_for)
    )
    assert retried is not None
    assert retried.status == "retryable"
    assert retried.run_id == failed.run_id
    assert retried.manual_retries == 1

    # Reusing the action without another terminal failure cannot create a run.
    refused = client.post(path, headers=HEADERS, json=body)
    assert refused.status_code in {400, 409}

    drift_due = DUE + timedelta(hours=1)
    drifted = asyncio.run(
        _terminal_failed(store, workflow, due=drift_due)
    )
    drift_path = (
        "/v1/workflows/daily/schedule/occurrences/"
        f"{quote(drifted.scheduled_for.isoformat(), safe='')}/retry"
    )
    drift_body = {"run_id": drifted.run_id}
    drift_held = client.post(drift_path, headers=HEADERS, json=drift_body)
    assert drift_held.status_code == 202
    drift_approval = drift_held.json()["hitl_request_id"]
    asyncio.run(
        store.upsert_workflow(
            WorkflowDefinition(
                **{
                    **workflow.__dict__,
                    "definition": {
                        "steps": [],
                        "changed_after_approval": True,
                    },
                }
            )
        )
    )
    asyncio.run(
        kernel.hitl.answer(
            T, drift_approval, "approve", "independent-reviewer"
        )
    )
    drift_replay = client.post(
        drift_path,
        headers=HEADERS,
        json={**drift_body, "approval_id": drift_approval},
    )
    assert drift_replay.status_code in {400, 403, 409}
    unchanged = asyncio.run(
        store.get_workflow_schedule_occurrence(
            T, workflow.id, drifted.scheduled_for
        )
    )
    assert unchanged is not None and unchanged.status == "failed"


class _DurableExecutor:
    durable = True


class _WorkflowSink:
    def __init__(
        self,
        store: InMemoryStore | None = None,
        *,
        settle_before_return: bool = False,
    ) -> None:
        self.run_ids: list[str] = []
        self.store = store
        self.settle_before_return = settle_before_return

    async def trigger(self, tenant, workflow_id, inputs, **kwargs):
        self.run_ids.append(kwargs["run_id"])
        if self.settle_before_return:
            assert self.store is not None
            assert await self.store.finish_workflow_schedule_outcome(
                tenant,
                kwargs["run_id"],
                status="succeeded",
                reason=None,
            )
        return {
            "run_id": kwargs["run_id"],
            "engine_run_id": f"engine:{kwargs['run_id']}",
            "status": "queued",
        }


@pytest.mark.security
@pytest.mark.invariant("FR-WFL-21")
async def test_retry_reconciliation_reuses_the_canonical_run_id() -> None:
    _, store, workflow = await _setup()
    failed = await _terminal_failed(store, workflow)
    schedule = await store.get_workflow_schedule(T, workflow.id)
    assert schedule is not None
    retried = await store.request_workflow_schedule_occurrence_retry(
        T,
        workflow.id,
        failed.scheduled_for,
        run_id=failed.run_id,
        workflow_sha256=workflow_snapshot_digest(workflow),
        schedule_sha256=workflow_schedule_digest(schedule),
        max_manual_retries=3,
    )
    assert retried is not None
    sink = _WorkflowSink()
    assert await reconcile_workflow_schedules(
        store,
        T,
        sink,
        executor=_DurableExecutor(),
        now=DUE,
    ) == 1
    current = await store.get_workflow_schedule_occurrence(
        T, workflow.id, failed.scheduled_for
    )
    assert current is not None
    assert current.status == "queued"
    assert current.run_id == failed.run_id
    assert sink.run_ids == [failed.run_id]

    race_due = failed.scheduled_for + timedelta(hours=1)
    raced_failed = await _terminal_failed(store, workflow, due=race_due)
    raced_retry = await store.request_workflow_schedule_occurrence_retry(
        T,
        workflow.id,
        raced_failed.scheduled_for,
        run_id=raced_failed.run_id,
        workflow_sha256=workflow_snapshot_digest(workflow),
        schedule_sha256=workflow_schedule_digest(schedule),
        max_manual_retries=3,
    )
    assert raced_retry is not None
    racing_sink = _WorkflowSink(store, settle_before_return=True)
    assert await reconcile_workflow_schedules(
        store,
        T,
        racing_sink,
        executor=_DurableExecutor(),
        now=DUE,
    ) == 1
    raced = await store.get_workflow_schedule_occurrence(
        T, workflow.id, raced_failed.scheduled_for
    )
    assert raced is not None and raced.status == "succeeded"
    assert racing_sink.run_ids == [raced_failed.run_id]


@pytest.mark.security
@pytest.mark.invariant("FR-WFL-21")
async def test_workflow_task_body_settles_terminal_schedule_outcomes(
    monkeypatch,
) -> None:
    kernel, store, workflow = await _setup()
    failed = await _terminal_failed(store, workflow)
    schedule = await store.get_workflow_schedule(T, workflow.id)
    assert schedule is not None
    retried = await store.request_workflow_schedule_occurrence_retry(
        T,
        workflow.id,
        failed.scheduled_for,
        run_id=failed.run_id,
        workflow_sha256=workflow_snapshot_digest(workflow),
        schedule_sha256=workflow_schedule_digest(schedule),
        max_manual_retries=3,
    )
    assert retried is not None
    claimed, won = await store.claim_workflow_schedule_occurrence(
        WorkflowScheduleOccurrence(
            **{**retried.__dict__, "lease_owner": "scheduler-b"}
        ),
        lease_seconds=60,
    )
    assert won
    assert await store.finish_workflow_schedule_occurrence(
        T,
        workflow.id,
        failed.scheduled_for,
        lease_owner=claimed.lease_owner,
        status="queued",
        engine_run_id="engine-run",
        reason=None,
    )
    context = InvocationContext(
        tenant_id=T,
        actor=AUTHOR,
        on_behalf_of=AUTHOR,
        grants=GrantSet.of(["*"]),
    )
    payload = {
        "tenant": T,
        "workflow_id": workflow.id,
        "workflow_snapshot": build_workflow_snapshot(workflow),
        "inputs": {},
        "ctx_envelope": context_to_envelope(context),
        "run_id": failed.run_id,
    }

    async def paused(*args, **kwargs):
        return {"status": "paused", "run_id": failed.run_id}

    monkeypatch.setattr(
        "boltrig.workflows.interpreter.run_workflow_definition", paused
    )
    await run_workflow_body(kernel, payload)
    pending = await store.get_workflow_schedule_occurrence(
        T, workflow.id, failed.scheduled_for
    )
    assert pending is not None and pending.status == "queued"

    async def completed(*args, **kwargs):
        return {"status": "completed", "run_id": failed.run_id}

    monkeypatch.setattr(
        "boltrig.workflows.interpreter.run_workflow_definition", completed
    )
    await run_workflow_body(kernel, payload)
    succeeded = await store.get_workflow_schedule_occurrence(
        T, workflow.id, failed.scheduled_for
    )
    assert succeeded is not None
    assert succeeded.status == "succeeded"
    assert succeeded.outcome_at is not None

    second_due = DUE + timedelta(hours=1)
    second = await _terminal_failed(store, workflow, due=second_due)
    retried_second = await store.request_workflow_schedule_occurrence_retry(
        T,
        workflow.id,
        second.scheduled_for,
        run_id=second.run_id,
        workflow_sha256=workflow_snapshot_digest(workflow),
        schedule_sha256=workflow_schedule_digest(schedule),
        max_manual_retries=3,
    )
    assert retried_second is not None
    claimed_second, won = await store.claim_workflow_schedule_occurrence(
        WorkflowScheduleOccurrence(
            **{**retried_second.__dict__, "lease_owner": "scheduler-c"}
        ),
        lease_seconds=60,
    )
    assert won
    assert await store.finish_workflow_schedule_occurrence(
        T,
        workflow.id,
        second.scheduled_for,
        lease_owner=claimed_second.lease_owner,
        status="queued",
        engine_run_id="engine-run-2",
        reason=None,
    )

    async def execution_failed(*args, **kwargs):
        return {"status": "failed", "run_id": second.run_id}

    monkeypatch.setattr(
        "boltrig.workflows.interpreter.run_workflow_definition",
        execution_failed,
    )
    await run_workflow_body(kernel, {**payload, "run_id": second.run_id})
    settled_failed = await store.get_workflow_schedule_occurrence(
        T, workflow.id, second.scheduled_for
    )
    assert settled_failed is not None
    assert settled_failed.status == "failed"
    assert settled_failed.reason == "workflow_execution_failed"
    assert settled_failed.outcome_at is not None
    # At-least-once delivery can leave two same-run task attempts. A later
    # successful terminal result upgrades a failed one; a failure can never
    # downgrade an already successful logical run.
    assert await store.finish_workflow_schedule_outcome(
        T, second.run_id, status="succeeded", reason=None
    )
    upgraded = await store.get_workflow_schedule_occurrence(
        T, workflow.id, second.scheduled_for
    )
    assert upgraded is not None and upgraded.status == "succeeded"
    assert not await store.finish_workflow_schedule_outcome(
        T,
        second.run_id,
        status="failed",
        reason="workflow_execution_failed",
    )

    # A fast task may finish before the scheduler stores its enqueue receipt.
    # The task settles the same claimed row; the later enqueue CAS then loses
    # harmlessly instead of overwriting the real outcome.
    race_due = DUE + timedelta(hours=2)
    race_run_id = scheduled_run_id(T, workflow.id, race_due)
    race_claim, won = await store.claim_workflow_schedule_occurrence(
        WorkflowScheduleOccurrence(
            tenant_id=T,
            workflow_id=workflow.id,
            scheduled_for=race_due,
            run_id=race_run_id,
            status="claimed",
            lease_owner="scheduler-race",
            workflow_sha256=workflow_snapshot_digest(workflow),
            schedule_sha256=workflow_schedule_digest(schedule),
        ),
        lease_seconds=60,
    )
    assert won
    monkeypatch.setattr(
        "boltrig.workflows.interpreter.run_workflow_definition", completed
    )
    await run_workflow_body(kernel, {**payload, "run_id": race_run_id})
    raced = await store.get_workflow_schedule_occurrence(
        T, workflow.id, race_due
    )
    assert raced is not None and raced.status == "succeeded"
    assert not await store.finish_workflow_schedule_occurrence(
        T,
        workflow.id,
        race_due,
        lease_owner=race_claim.lease_owner,
        status="queued",
        engine_run_id="late-engine-receipt",
        reason=None,
    )

    # A task exception is not called terminal because Hatchet may retry it.
    exception_due = DUE + timedelta(hours=3)
    exception_run_id = scheduled_run_id(T, workflow.id, exception_due)
    _, won = await store.claim_workflow_schedule_occurrence(
        WorkflowScheduleOccurrence(
            tenant_id=T,
            workflow_id=workflow.id,
            scheduled_for=exception_due,
            run_id=exception_run_id,
            status="claimed",
            lease_owner="scheduler-exception",
            workflow_sha256=workflow_snapshot_digest(workflow),
            schedule_sha256=workflow_schedule_digest(schedule),
        ),
        lease_seconds=60,
    )
    assert won

    async def infrastructure_error(*args, **kwargs):
        raise RuntimeError("transient task failure")

    monkeypatch.setattr(
        "boltrig.workflows.interpreter.run_workflow_definition",
        infrastructure_error,
    )
    with pytest.raises(RuntimeError, match="transient task failure"):
        await run_workflow_body(
            kernel, {**payload, "run_id": exception_run_id}
        )
    still_in_flight = await store.get_workflow_schedule_occurrence(
        T, workflow.id, exception_due
    )
    assert still_in_flight is not None
    assert still_in_flight.status == "claimed"
    assert still_in_flight.outcome_at is None
    assert await store.finish_workflow_schedule_occurrence(
        T,
        workflow.id,
        exception_due,
        lease_owner="scheduler-exception",
        status="queued",
        engine_run_id="engine-exception",
        reason=None,
    )
    client = TestClient(create_app(kernel))
    receipts = client.get(
        "/v1/workflows/daily/schedule/occurrences?limit=50",
        headers=HEADERS,
    ).json()["occurrences"]
    unknown = next(
        item for item in receipts if item["run_id"] == exception_run_id
    )
    assert unknown["status"] == "enqueued"
    assert unknown["outcome_at"] is None
    assert unknown["engine_outcome"] == {
        "status": "pending_or_unknown",
        "recovery": "engine_terminal_reconciliation_unavailable",
    }
