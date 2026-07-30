"""Security and durability contract for canonical workflow scheduling."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from boltrig.kernel.platform_routes.workflows import _lifecycle
from boltrig.models import (
    GrantSet,
    User,
    WorkflowDefinition,
    WorkflowSchedule,
    WorkflowSource,
)
from boltrig.store import InMemoryStore
from boltrig.workflows.scheduler import (
    next_cron_occurrence,
    reconcile_workflow_schedules,
)

T = "schedule-tenant"
NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


class _Executor:
    def __init__(self, *, durable: bool = True):
        self.durable = durable


class _WorkerCrash(BaseException):
    pass


class _WorkflowSink:
    def __init__(self, *, crash_after_accept_once: bool = False):
        self.calls: list[dict] = []
        self.crash_after_accept_once = crash_after_accept_once

    async def trigger(self, tenant, workflow_id, inputs, **kwargs):
        self.calls.append(
            {
                "tenant": tenant,
                "workflow_id": workflow_id,
                "inputs": inputs,
                **kwargs,
            }
        )
        await asyncio.sleep(0)
        if self.crash_after_accept_once:
            self.crash_after_accept_once = False
            raise _WorkerCrash()
        return {
            "run_id": kwargs["run_id"],
            "engine_run_id": f"engine:{kwargs['run_id']}",
            "status": "queued",
        }


async def _store(
    *,
    captured: GrantSet | None = None,
    current_scope: dict | None = None,
    authority_subject: str | None = "author",
    next_due_at: datetime | None = None,
) -> InMemoryStore:
    store = InMemoryStore()
    await store.upsert_workflow(
        WorkflowDefinition(
            id="daily",
            tenant_id=T,
            version="1",
            source=WorkflowSource.PRECREATED,
            definition={"steps": []},
        )
    )
    if authority_subject is not None:
        await store.upsert_user(
            User(
                id=authority_subject,
                tenant_id=T,
                role="member",
                scope=current_scope or {
                    "verbs": ["control.workflow.trigger"]
                },
            )
        )
    await store.upsert_workflow_schedule(
        WorkflowSchedule(
            tenant_id=T,
            workflow_id="daily",
            workspace_id=None,
            cron="* * * * *",
            timezone="UTC",
            authority_subject=authority_subject,
            grant_ceiling=captured
            or GrantSet.of(["control.workflow.trigger"]),
            next_due_at=next_due_at or NOW - timedelta(minutes=1),
        )
    )
    return store


@pytest.mark.security
@pytest.mark.invariant("FR-WFL-20")
@pytest.mark.parametrize(
    ("captured", "current_scope"),
    [
        (
            GrantSet.of(["control.workflow.trigger"]),
            {"all": True},
        ),
        (
            GrantSet.of(["*"]),
            {"verbs": ["control.workflow.trigger"]},
        ),
    ],
)
async def test_schedule_reauthorizes_current_grants_intersected_with_captured_ceiling(
    captured, current_scope
) -> None:
    store = await _store(captured=captured, current_scope=current_scope)
    sink = _WorkflowSink()

    assert await reconcile_workflow_schedules(
        store, T, sink, executor=_Executor(), now=NOW, max_catch_up=1
    ) == 1
    context = sink.calls[0]["context"]
    assert context.actor == context.on_behalf_of == "author"
    assert context.actor_tier == "human"
    assert context.grants.allow == ("control.workflow.trigger",)
    assert context.grants.permits("control.workflow.trigger")
    assert not context.grants.permits("control.workflow.schedule")


@pytest.mark.security
@pytest.mark.invariant("FR-WFL-20")
async def test_missing_authority_and_non_durable_executor_are_observed_not_invented() -> None:
    no_authority = await _store(authority_subject=None)
    sink = _WorkflowSink()
    await reconcile_workflow_schedules(
        no_authority, T, sink, executor=_Executor(), now=NOW
    )
    state = await no_authority.get_workflow_schedule(T, "daily")
    assert state is not None
    assert (state.observed_status, state.observed_reason) == (
        "needs_action",
        "scheduling_authority_not_bound",
    )
    assert sink.calls == []

    non_durable = await _store()
    await reconcile_workflow_schedules(
        non_durable, T, sink, executor=_Executor(durable=False), now=NOW
    )
    state = await non_durable.get_workflow_schedule(T, "daily")
    assert state is not None
    assert (state.observed_status, state.observed_reason) == (
        "unavailable",
        "durable_executor_required",
    )
    assert sink.calls == []


@pytest.mark.security
@pytest.mark.invariant("FR-WFL-20")
async def test_replicas_claim_once_restart_does_not_duplicate_a_terminal_occurrence() -> None:
    store = await _store()
    sink = _WorkflowSink()
    results = await asyncio.gather(
        reconcile_workflow_schedules(
            store,
            T,
            sink,
            executor=_Executor(),
            now=NOW,
            worker_id="replica-a",
            max_catch_up=1,
        ),
        reconcile_workflow_schedules(
            store,
            T,
            sink,
            executor=_Executor(),
            now=NOW,
            worker_id="replica-b",
            max_catch_up=1,
        ),
    )
    assert sum(results) == 1
    assert len(sink.calls) == 1

    await reconcile_workflow_schedules(
        store,
        T,
        sink,
        executor=_Executor(),
        now=NOW,
        worker_id="after-restart",
        max_catch_up=1,
    )
    assert len(sink.calls) == 1


@pytest.mark.security
@pytest.mark.invariant("FR-WFL-20")
async def test_ambiguous_enqueue_reclaim_is_at_least_once_with_one_logical_run_id() -> None:
    store = await _store()
    sink = _WorkflowSink(crash_after_accept_once=True)

    with pytest.raises(_WorkerCrash):
        await reconcile_workflow_schedules(
            store,
            T,
            sink,
            executor=_Executor(),
            now=NOW,
            worker_id="crashed-worker",
            lease_seconds=1,
            max_catch_up=1,
        )
    await asyncio.sleep(1.01)
    assert await reconcile_workflow_schedules(
        store,
        T,
        sink,
        executor=_Executor(),
        now=NOW,
        worker_id="replacement-worker",
        max_catch_up=1,
    ) == 1

    # Engine submission is at-least-once across this unavoidable transaction
    # boundary, but every replay carries the same durable logical run identity.
    assert len(sink.calls) == 2
    assert sink.calls[0]["run_id"] == sink.calls[1]["run_id"]
    due = NOW - timedelta(minutes=1)
    occurrence = await store.get_workflow_schedule_occurrence(T, "daily", due)
    assert occurrence is not None
    assert occurrence.status == "queued"
    assert occurrence.attempts == 2


@pytest.mark.security
@pytest.mark.invariant("FR-WFL-20")
async def test_missed_occurrence_catch_up_is_bounded_and_reports_truncation() -> None:
    store = await _store(next_due_at=NOW - timedelta(minutes=5))
    sink = _WorkflowSink()

    assert await reconcile_workflow_schedules(
        store,
        T,
        sink,
        executor=_Executor(),
        now=NOW,
        max_catch_up=2,
    ) == 2
    state = await store.get_workflow_schedule(T, "daily")
    assert state is not None
    assert state.next_due_at > NOW
    assert (state.observed_status, state.observed_reason) == (
        "degraded",
        "missed_occurrences_truncated",
    )


@pytest.mark.security
@pytest.mark.invariant("FR-WFL-20")
def test_timezone_cron_handles_dst_gaps_folds_and_standard_dom_dow_or() -> None:
    # The missing 01:30 local wall time is skipped on spring-forward.
    assert next_cron_occurrence(
        "0 30 1 * * *",
        "Europe/London",
        datetime(2026, 3, 29, 0, 30, tzinfo=UTC),
    ) == datetime(2026, 3, 30, 0, 30, tzinfo=UTC)

    # The repeated fall-back wall time has two distinct UTC occurrences.
    first = next_cron_occurrence(
        "0 30 1 * * *",
        "Europe/London",
        datetime(2026, 10, 24, 23, 0, tzinfo=UTC),
    )
    second = next_cron_occurrence(
        "0 30 1 * * *", "Europe/London", first
    )
    assert (first, second) == (
        datetime(2026, 10, 25, 0, 30, tzinfo=UTC),
        datetime(2026, 10, 25, 1, 30, tzinfo=UTC),
    )

    # When both day-of-month and day-of-week are restricted, cron uses OR.
    assert next_cron_occurrence(
        "0 9 1 * MON", "UTC", datetime(2026, 7, 2, tzinfo=UTC)
    ) == datetime(2026, 7, 6, 9, tzinfo=UTC)
    assert next_cron_occurrence(
        "0 9 1 * MON", "UTC", datetime(2026, 7, 30, tzinfo=UTC)
    ) == datetime(2026, 8, 1, 9, tzinfo=UTC)


@pytest.mark.security
@pytest.mark.invariant("FR-WFL-20")
def test_legacy_definition_schedule_projects_needs_action() -> None:
    workflow = WorkflowDefinition(
        id="legacy",
        tenant_id=T,
        version="1",
        source=WorkflowSource.PRECREATED,
        definition={
            "schedule": {
                "type": "cron",
                "cron": "0 9 * * *",
                "timezone": "UTC",
            }
        },
    )
    projected = _lifecycle(workflow)
    assert projected["schedule"]["cron"] == "0 9 * * *"
    assert projected["schedule_state"]["desired"]["status"] == "active"
    assert projected["schedule_state"]["observed"] == {
        "status": "needs_action",
        "reason": "scheduling_authority_not_bound",
        "next_run_at": None,
        "last_scheduled_for": None,
        "observed_at": None,
    }
