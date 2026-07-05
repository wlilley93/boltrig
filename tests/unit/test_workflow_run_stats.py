"""Workflow run records (design brief 22.1): record_workflow_run +
workflow_run_stats on the in-memory store.

The automations home cards read aggregated stats (run_count, success_count,
last_run_at) from this seam. The load-bearing properties are: per-workflow
aggregation, success = status == "completed", tenant isolation, and idempotent
re-recording of the same run_id (no double count, original started_at kept).
Offline: InMemoryStore, no postgres.
"""

from datetime import datetime, timezone

from boltrig.store import InMemoryStore

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
    assert second[0]["success_count"] == 0
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
