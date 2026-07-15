"""Durable delegation (Beat 3): lease-based work-item claims (US-FLT-05),
atomic store-backed fan-out counters (US-EXE-07), run checkpoints, and faithful
round-trips of the new work-item fields (US-FLT-07 persistence).

Same parity pattern as test_store_parity: ONE set of contract assertions runs
against BOTH backends; the memory backend runs everywhere, the postgres backend
runs when BOLTRIG_TEST_DATABASE_URL is set (CI) and skips cleanly offline.
"""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta

import pytest

from boltrig.models import WorkItem, WorkStatus, utcnow

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
T = "acme"
_TABLES = "work_items,run_checkpoints,fanout_counters"


async def _make_store(kind: str):
    if kind == "memory":
        from boltrig.store import InMemoryStore

        return InMemoryStore()
    from boltrig.store import PostgresStore

    store = await PostgresStore.connect(DSN)
    await store._pool.execute(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE")
    return store


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(
                not DSN, reason="set BOLTRIG_TEST_DATABASE_URL for Postgres parity"
            ),
        ),
    ]
)
async def store(request):
    s = await _make_store(request.param)
    yield s
    close = getattr(s, "close", None)
    if close is not None:
        await close()


def _item(item_id: str, **kw) -> WorkItem:
    return WorkItem(
        id=item_id,
        tenant_id=T,
        source="internal",
        intent=f"do {item_id}",
        confidence=0.9,
        convergent=True,
        **kw,
    )


# --- lease-based claim (US-FLT-05) ------------------------------------------
@pytest.mark.store
@pytest.mark.invariant("US-FLT-05")
async def test_pending_item_claimed_exactly_once_concurrently(store):
    await store.create_work_item(_item("w1"))
    a, b = await asyncio.gather(
        store.claim_work_item(T, "worker-a", 60),
        store.claim_work_item(T, "worker-b", 60),
    )
    winners = [w for w in (a, b) if w is not None]
    assert len(winners) == 1  # exactly one winner across concurrent claimers
    won = winners[0]
    assert won.id == "w1"
    assert won.status == WorkStatus.IN_FLIGHT
    assert won.lease_owner in ("worker-a", "worker-b")
    assert won.lease_expires_at is not None
    assert won.attempts == 1
    # the item is spent: a third claim finds nothing claimable
    assert await store.claim_work_item(T, "worker-c", 60) is None


@pytest.mark.store
@pytest.mark.invariant("US-FLT-05")
async def test_expired_lease_is_reclaimable_and_attempts_increment(store):
    await store.create_work_item(_item("w1"))
    first = await store.claim_work_item(T, "worker-a", 60)
    assert first is not None and first.attempts == 1
    # a live lease is not reclaimable
    assert await store.claim_work_item(T, "worker-b", 60) is None
    # expire the lease (the worker died mid-run)
    first.lease_expires_at = utcnow() - timedelta(seconds=5)
    await store.update_work_item(first)
    second = await store.claim_work_item(T, "worker-b", 60)
    assert second is not None
    assert second.id == "w1"
    assert second.lease_owner == "worker-b"
    assert second.lease_expires_at > utcnow()
    assert second.attempts == 2


@pytest.mark.store
@pytest.mark.invariant("US-FLT-05")
async def test_claim_is_tenant_scoped_and_skips_unclaimable(store):
    await store.create_work_item(_item("w-done", status=WorkStatus.DONE))
    await store.create_work_item(_item("w-blocked", status=WorkStatus.BLOCKED))
    assert await store.claim_work_item(T, "worker-a", 60) is None
    await store.create_work_item(_item("w-pending"))
    assert await store.claim_work_item("other-tenant", "worker-a", 60) is None
    claimed = await store.claim_work_item(T, "worker-a", 60)
    assert claimed is not None and claimed.id == "w-pending"


# --- atomic fan-out counters (US-EXE-07) ------------------------------------
@pytest.mark.store
@pytest.mark.invariant("US-EXE-07")
async def test_fanout_cap_refuses_the_increment_past_cap(store):
    cap = 3
    for _ in range(cap):
        assert await store.try_increment_fanout(T, "tree1", "children", 1, cap) is True
    # the cap+1th increment is refused (and nothing is applied)
    assert await store.try_increment_fanout(T, "tree1", "children", 1, cap) is False
    # a fresh counter whose first increment exceeds the cap is refused too
    assert await store.try_increment_fanout(T, "tree2", "children", cap + 1, cap) is False
    # counters are independent per (tree, counter) and per tenant
    assert await store.try_increment_fanout(T, "tree1", "depth", 1, cap) is True
    assert await store.try_increment_fanout("other", "tree1", "children", 1, cap) is True


@pytest.mark.store
@pytest.mark.invariant("US-EXE-07")
async def test_fanout_cap_holds_under_concurrent_increments(store):
    cap = 3
    results = await asyncio.gather(
        *(store.try_increment_fanout(T, "tree1", "children", 1, cap) for _ in range(8))
    )
    assert sum(results) == cap  # exactly cap succeed, the rest are refused


# --- run checkpoints (the Beat 4 resume seam) --------------------------------
@pytest.mark.store
async def test_checkpoint_upsert_is_idempotent_and_lists_per_run(store):
    await store.upsert_checkpoint(T, "run1", "plan", "started")
    await store.upsert_checkpoint(T, "run1", "execute", "awaiting_human",
                                  hitl_request_id="hitl-9")
    await store.upsert_checkpoint(T, "run2", "plan", "done")
    # re-upserting the same (run, step) replaces, never duplicates
    await store.upsert_checkpoint(T, "run1", "plan", "done", output={"n": 2})
    rows = await store.list_checkpoints(T, "run1")
    assert sorted(c.step for c in rows) == ["execute", "plan"]
    by_step = {c.step: c for c in rows}
    assert by_step["plan"].status == "done"
    assert by_step["plan"].output == {"n": 2}
    assert by_step["execute"].hitl_request_id == "hitl-9"
    # tenant-scoped: another tenant sees nothing
    assert await store.list_checkpoints("other", "run1") == []


# --- new work-item fields round-trip (US-FLT-07 persistence) -----------------
@pytest.mark.store
@pytest.mark.invariant("US-FLT-07")
@pytest.mark.invariant("SEC-141")
async def test_work_item_degraded_result_attempts_roundtrip(store):
    lease_until = utcnow() + timedelta(seconds=60)
    await store.create_work_item(_item(
        "w1",
        status=WorkStatus.DONE,
        attempts=2,
        degraded=True,
        result={"summary": "done, degraded echo"},
        lease_owner="worker-a",
        lease_expires_at=lease_until,
        workspace_id="ws-1",
    ))
    got = await store.get_work_item(T, "w1")
    assert got is not None
    assert got.attempts == 2
    assert got.degraded is True
    assert got.result == {"summary": "done, degraded echo"}
    assert got.lease_owner == "worker-a"
    assert got.lease_expires_at == lease_until
    assert got.workspace_id == "ws-1"


@pytest.mark.store
@pytest.mark.invariant("SEC-142")
async def test_work_item_workspace_scope_filters_before_pagination(store):
    items = (
        _item("a-org", hatchet_run_id="run-org"),
        _item("b-ws1", hatchet_run_id="run-ws1", workspace_id="ws-1"),
        _item("c-ws2", hatchet_run_id="run-ws2", workspace_id="ws-2"),
        _item("collision", workspace_id="ws-2"),
        _item("visible-alias", hatchet_run_id="collision", workspace_id="ws-1"),
    )
    for item in items:
        await store.create_work_item(item)

    async def ids(**kwargs):
        return {item.id for item in await store.list_work_items(T, **kwargs)}

    assert await ids() == {item.id for item in items}
    assert await ids(enforce_workspace=True) == {"a-org"}
    assert await ids(workspace_id="ws-1", enforce_workspace=True) == {
        "a-org",
        "b-ws1",
        "visible-alias",
    }
    paged = await store.list_work_items(
        T, limit=2, workspace_id="ws-2", enforce_workspace=True
    )
    paged_ids = {item.id for item in paged}
    # Both backends must filter before LIMIT. Their configured string collations
    # may order '-' and letters differently, so pin membership rather than locale.
    assert len(paged_ids) == 2
    assert "a-org" in paged_ids
    assert paged_ids <= {"a-org", "c-ws2", "collision"}

    assert await store.get_work_item(
        T, "b-ws1", workspace_id="ws-1", enforce_workspace=True
    ) is not None
    assert await store.get_work_item(
        T, "c-ws2", workspace_id="ws-1", enforce_workspace=True
    ) is None
    assert await store.get_work_item_by_run_id(
        T, "run-ws1", workspace_id="ws-1", enforce_workspace=True
    ) is not None
    assert await store.get_work_item_by_run_id(
        T, "run-ws2", workspace_id="ws-1", enforce_workspace=True
    ) is None
    # A hidden direct id wins over a visible hatchet alias; filtering cannot make
    # lookup fall through to a different run with the same external identifier.
    assert await store.get_work_item_by_run_id(
        T, "collision", workspace_id="ws-1", enforce_workspace=True
    ) is None
