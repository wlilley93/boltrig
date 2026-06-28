"""PostgresStore: the kernel guarantees + durability hold on real Postgres (P0-1).

These run only when NANKLE_TEST_DATABASE_URL points at a Postgres (CI provides a
service; offline they skip cleanly, P9). They prove the security-relevant kernel
behaviours behave identically on the durable store, that state survives a
reconnect (restart), and that apply_manifest's async seed path works.
"""

from __future__ import annotations

import inspect
import os
from dataclasses import replace

import pytest

from nankle.adapters.builtin.memory_tickets import build as build_tickets
from nankle.kernel import Kernel
from nankle.models import (
    BindingNotFound,
    Budget,
    BudgetExceeded,
    GrantMissing,
    GrantSet,
    InvocationContext,
    PendingHuman,
    TenantPermissions,
    WorkItem,
    WorkStatus,
)
from nankle.store import InMemoryStore

DSN = os.environ.get("NANKLE_TEST_DATABASE_URL")
_pg = pytest.mark.skipif(not DSN, reason="set NANKLE_TEST_DATABASE_URL for Postgres tests")
T = "acme"
_TABLES = (
    "nouns,verbs,verb_bindings,adapters,skills,agent_capabilities,workflow_definitions,"
    "model_endpoints,work_items,hitl_requests,hitl_responses,audit_log,budgets,"
    "idempotency_keys,credential_refs,tenant_permissions"
)


async def _fresh_pg():
    from nankle.store import PostgresStore

    store = await PostgresStore.connect(DSN)
    await store._pool.execute(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE")
    return store


def _ctx(grants, tenant=T):
    return InvocationContext(
        tenant_id=tenant, grants=GrantSet.of(grants), actor="t", run_id="r1"
    )


async def _seed_perms(store, tenant, grants):
    res = store.set_tenant_permissions(TenantPermissions(tenant, GrantSet.of(grants)))
    if inspect.isawaitable(res):
        await res


async def _kernel_on(store):
    await _seed_perms(store, T, ["ticket.*"])
    k = Kernel(store)
    await k.register_adapter(T, build_tickets())
    return k


@_pg
async def test_pg_roundtrip_create_read():
    store = await _fresh_pg()
    try:
        k = await _kernel_on(store)
        created = await k.invoke("ticket", "ticket.create", {"title": "db"}, _ctx(["ticket.create"]))
        read = await k.invoke("ticket", "ticket.read", {"id": created["id"]}, _ctx(["ticket.read"]))
        assert read["id"] == created["id"]
    finally:
        await store.close()


@_pg
async def test_pg_grant_denied_and_audited():
    store = await _fresh_pg()
    try:
        k = await _kernel_on(store)
        with pytest.raises(GrantMissing):
            await k.invoke("ticket", "ticket.create", {"title": "x"}, _ctx([]))
        events = await store.audit_query(T)
        assert events[-1].status == "grant_missing"
    finally:
        await store.close()


@_pg
async def test_pg_audit_chain_verifies():
    store = await _fresh_pg()
    try:
        k = await _kernel_on(store)
        for i in range(3):
            await k.invoke("ticket", "ticket.create", {"title": f"t{i}"}, _ctx(["ticket.create"]))
        ok, bad = await k.audit.verify(T)
        assert ok and bad is None
    finally:
        await store.close()


@_pg
async def test_pg_budget_hard_stop():
    store = await _fresh_pg()
    try:
        k = await _kernel_on(store)
        await store.set_budget(
            Budget(id="dept:eng", tenant_id=T, scope_type="department",
                   cost_limit_micros=1000, hard_stop=True)
        )
        await k.cost.reserve(T, ["dept:eng"], tokens=0, micros=900)
        with pytest.raises(BudgetExceeded):
            await k.cost.reserve(T, ["dept:eng"], tokens=0, micros=200)
    finally:
        await store.close()


@_pg
async def test_pg_durability_across_reconnect():
    """A work item written, then read after a fresh connection (a restart)."""
    from nankle.store import PostgresStore

    store = await _fresh_pg()
    await store.create_work_item(
        WorkItem(id="w1", tenant_id=T, source="internal", intent="persist me",
                 confidence=0.9, convergent=True, status=WorkStatus.PENDING,
                 owner_member="engineering")
    )
    await store.close()  # drop the pool entirely

    store2 = await PostgresStore.connect(DSN)  # reconnect = restart
    try:
        items = await store2.list_work_items(T)
        assert any(w.id == "w1" and w.intent == "persist me" for w in items)
    finally:
        await store2.close()


@_pg
async def test_pg_apply_manifest_async_seed():
    """apply_manifest's seed helpers work against the async Postgres store."""
    from nankle.config import apply_manifest, load_manifest

    store = await _fresh_pg()
    try:
        m = load_manifest("manifest.example.yaml")
        k = Kernel(store, blocking_verbs=m.blocking_verbs())
        await apply_manifest(k, m)
        perms = await store.get_tenant_permissions(m.tenant_id)
        assert perms.grants.permits("ticket.create")
        assert await store.list_capabilities(m.tenant_id)
        disco = await k.discover(m.tenant_id)
        assert any(v["id"] == "ticket.create" for v in disco["verbs"])
    finally:
        await store.close()


@pytest.mark.security
@pytest.mark.invariant("SEC-08")
@pytest.mark.parametrize("store_kind", ["memory", pytest.param("postgres", marks=_pg)])
async def test_cross_tenant_fails_closed(store_kind):
    """Tenant isolation holds identically on both stores (SEC-08, K-22)."""
    store = InMemoryStore() if store_kind == "memory" else await _fresh_pg()
    try:
        k = await _kernel_on(store)
        await _seed_perms(store, "other", ["ticket.*"])
        assert (await k.discover("other"))["verbs"] == []  # foreign tenant sees nothing
        octx = replace(_ctx(["ticket.create"]), tenant_id="other")
        with pytest.raises(BindingNotFound):  # foreign dispatch fails closed
            await k.invoke("ticket", "ticket.create", {"title": "x"}, octx)
    finally:
        if store_kind == "postgres":
            await store.close()


@_pg
@pytest.mark.invariant("NFR-REL-01")
async def test_blocking_pause_survives_restart_and_resumes():
    """A blocking HITL pause is durable: it survives a restart and then resumes
    the work to completion on approval (NFR-REL-01, the core durability property).

    The full live-Hatchet run-resume is the production backbone (a CI-gated
    end-to-end); here the durable record (the pending HITL request + the approval)
    lives in Postgres, so a fresh process picks the pause up and resumes it."""
    from nankle.adapters.builtin.memory_tickets import build as build_tickets
    from nankle.store import PostgresStore

    store1 = await _fresh_pg()
    await _seed_perms(store1, T, ["ticket.*"])
    k1 = Kernel(store1, blocking_verbs={"ticket.create"})
    await k1.register_adapter(T, build_tickets())
    with pytest.raises(PendingHuman) as exc:
        await k1.invoke("ticket", "ticket.create", {"title": "x"}, _ctx(["ticket.create"]))
    req_id = exc.value.hitl_request_id
    await store1.close()  # restart: drop the process/pool entirely

    store2 = await PostgresStore.connect(DSN)  # fresh process on the same database
    try:
        pending = await store2.list_pending_hitl(T)
        assert any(r.id == req_id for r in pending)  # the pause survived the restart
        k2 = Kernel(store2, blocking_verbs={"ticket.create"})
        await k2.register_adapter(T, build_tickets())
        await k2.hitl.answer(T, req_id, "approve", "lead@acme")
        out = await k2.invoke(
            "ticket", "ticket.create", {"title": "x"}, _ctx(["ticket.create"]),
            approval_id=req_id,
        )
        assert out["status"] == "open"  # resumed to completion after approval
    finally:
        await store2.close()
