"""Workflow run records (design brief 22.1): record_workflow_run +
workflow_run_stats on the in-memory store, and the route-level guarantee that a
stats-recording failure NEVER breaks workflow execution.

The automations home cards read aggregated stats (run_count, success_count,
last_run_at) from this seam. The load-bearing properties are: per-workflow
aggregation, success = status == "completed", tenant isolation, idempotent
re-recording of the same run_id (no double count, original started_at kept),
and that execute is observability-only (a recording error is swallowed).
Offline: InMemoryStore, no postgres.
"""

import asyncio
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.fleet.workers import LocalDurableExecutor
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    GrantSet,
    TenantPermissions,
    WorkflowDefinition,
    WorkflowSource,
)
from boltrig.store import InMemoryStore
from boltrig.workflows import WorkflowLibrary
from tests.approval import approved_request

T = "acme"
OTHER = "globex"


async def test_record_and_stats_counts_runs_per_workflow():
    store = InMemoryStore()
    await store.record_workflow_run(T, "smoke-loop", "r1", "completed")
    await store.record_workflow_run(T, "smoke-loop", "r2", "completed")
    await store.record_workflow_run(T, "smoke-loop", "r3", "failed")
    await store.record_workflow_run(T, "smoke-cf", "r4", "completed")

    stats = await store.workflow_run_stats(T)
    by_id = {s["workflow_id"]: s for s in stats}
    assert by_id["smoke-loop"]["run_count"] == 3
    assert by_id["smoke-loop"]["success_count"] == 2
    assert by_id["smoke-cf"]["run_count"] == 1
    assert by_id["smoke-cf"]["success_count"] == 1
    # ordered by workflow_id
    assert [s["workflow_id"] for s in stats] == ["smoke-cf", "smoke-loop"]


async def test_workflow_run_stats_is_tenant_scoped():
    store = InMemoryStore()
    await store.record_workflow_run(T, "smoke-loop", "r1", "completed")
    await store.record_workflow_run(OTHER, "smoke-loop", "rX", "completed")

    mine = await store.workflow_run_stats(T)
    theirs = await store.workflow_run_stats(OTHER)
    assert len(mine) == 1 and mine[0]["run_count"] == 1
    assert len(theirs) == 1 and theirs[0]["run_count"] == 1


async def test_record_workflow_run_is_idempotent_on_run_id():
    # A re-record of the same run_id is a no-op: it neither double-counts nor
    # bumps started_at forward (matches the postgres ON CONFLICT DO NOTHING).
    store = InMemoryStore()
    await store.record_workflow_run(T, "smoke-loop", "r1", "completed")
    first = await store.workflow_run_stats(T)
    first_at = first[0]["last_run_at"]
    assert isinstance(first_at, datetime)

    await store.record_workflow_run(T, "smoke-loop", "r1", "failed")
    second = await store.workflow_run_stats(T)
    assert second[0]["run_count"] == 1
    assert second[0]["success_count"] == 1
    assert second[0]["last_run_at"] == first_at


async def test_workflow_run_stats_empty_when_no_runs():
    store = InMemoryStore()
    assert await store.workflow_run_stats(T) == []


async def test_workflow_run_stats_last_run_at_is_max():
    store = InMemoryStore()
    await store.record_workflow_run(T, "smoke-loop", "r1", "completed")
    # Backdate the first row's started_at, then add a newer run; last_run_at
    # must be the max across the workflow's runs.
    store._workflow_runs[(T, "r1")] = ("smoke-loop", "completed",
                                       datetime(2020, 1, 1, tzinfo=timezone.utc))
    await store.record_workflow_run(T, "smoke-loop", "r2", "completed")
    stats = await store.workflow_run_stats(T)
    assert stats[0]["last_run_at"] == store._workflow_runs[(T, "r2")][2]


class _StatsBrokenStore(InMemoryStore):
    """InMemoryStore whose record_workflow_run always raises. Proves the route
    swallows a stats-recording failure so execute never fails."""

    async def record_workflow_run(self, tenant_id, workflow_id, run_id, status):
        raise RuntimeError("stats store is down")


def _seed(coro):
    return asyncio.run(coro)


def _execute_client():
    # Wire a kernel + WorkflowLibrary with one stored workflow, backed by a
    # store that BLOWS UP on record_workflow_run. The execute route must still
    # return the run record (observability-only, brief 22.1).
    store = _StatsBrokenStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    _seed(k.register_adapter(T, build_tickets()))
    lib = WorkflowLibrary(store, executor=LocalDurableExecutor(), kernel=k)
    wf = WorkflowDefinition(
        id="smoke-loop", tenant_id=T, version="1.0.0",
        source=WorkflowSource.PRECREATED,
        definition={"name": "smoke", "version": "1",
                    "steps": [{"id": "s1", "parents": [],
                               "action": "ticket.create", "params": {"title": "x"}}]},
        intent_tags=[],
    )
    _seed(lib.register(wf))
    return TestClient(create_app(k, platform={"workflows": lib})), k


def _h():
    return {"x-boltrig-tenant": T, "x-boltrig-subject": "dev",
            "x-boltrig-grants": "*", "x-boltrig-role": "org-admin"}


def test_execute_succeeds_even_when_record_workflow_run_raises():
    c, k = _execute_client()
    r = approved_request(
        c, k, T, "POST", "/v1/workflows/smoke-loop/execute",
        headers=_h(), json={"inputs": {}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["run_id"]
    # the broken store recorded nothing; stats endpoint still serves (empty)
    stats = c.get("/v1/workflow-stats", headers=_h()).json()
    assert stats == {"stats": []}


def test_workflow_stats_endpoint_returns_aggregated_rows():
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    platform = {"workflows": WorkflowLibrary(store, executor=LocalDurableExecutor(),
                                             kernel=k)}
    c = TestClient(create_app(k, platform=platform))
    # seed two runs directly through the store (the route path is covered above)
    _seed(store.record_workflow_run(T, "smoke-loop", "r1", "completed"))
    _seed(store.record_workflow_run(T, "smoke-loop", "r2", "failed"))
    body = c.get("/v1/workflow-stats", headers=_h()).json()
    assert body["stats"] == [
        {"workflow_id": "smoke-loop", "run_count": 2, "success_count": 1,
         "last_run_at": body["stats"][0]["last_run_at"]},
    ]
