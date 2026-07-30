"""PostgresStore: the kernel guarantees + durability hold on real Postgres (P0-1).

These run only when BOLTRIG_TEST_DATABASE_URL points at a Postgres (CI provides a
service; offline they skip cleanly, P9). They prove the security-relevant kernel
behaviours behave identically on the durable store, that state survives a
reconnect (restart), and that apply_manifest's async seed path works.
"""

from __future__ import annotations

import contextlib
import inspect
import os
from dataclasses import replace

import pytest

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.kernel import Kernel
from boltrig.models import (
    BindingNotFound,
    Budget,
    BudgetExceeded,
    GrantMissing,
    GrantSet,
    InvocationContext,
    PendingHuman,
    PermanentFleetObservation,
    TenantPermissions,
    WorkItem,
    WorkStatus,
)
from boltrig.store import InMemoryStore
from boltrig.store.idempotency_contract import IdempotencyClaimStatus

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
_pg = pytest.mark.skipif(not DSN, reason="set BOLTRIG_TEST_DATABASE_URL for Postgres tests")
T = "acme"
_TABLES = (
    "nouns,verbs,verb_bindings,adapters,skills,agent_capabilities,workflow_definitions,"
    "model_endpoints,work_items,hitl_requests,hitl_responses,audit_log,budgets,"
    "idempotency_keys,credential_refs,tenant_permissions"
    ",permanent_fleet_observations"
)


async def _fresh_pg():
    from boltrig.store import PostgresStore

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
@pytest.mark.invariant("SEC-WRK-27")
async def test_pg_permanent_fleet_observation_is_tenant_scoped_and_upserted():
    store = await _fresh_pg()
    try:
        await store.upsert_permanent_fleet_observation(
            PermanentFleetObservation(
                tenant_id=T,
                worker_id="worker-1",
                generation="pf_" + "a" * 24,
                status="degraded",
                inactive_fields=["purpose"],
            )
        )
        await store.upsert_permanent_fleet_observation(
            PermanentFleetObservation(
                tenant_id=T,
                worker_id="worker-1",
                generation="pf_" + "b" * 24,
                status="applied",
                applied_fields=["department_routing_identity"],
                inactive_fields=["purpose"],
            )
        )
        await store.upsert_permanent_fleet_observation(
            PermanentFleetObservation(
                tenant_id="other",
                worker_id="worker-1",
                generation="pf_" + "c" * 24,
                status="applied",
                applied_fields=["department_routing_identity"],
            )
        )
        rows = await store.list_permanent_fleet_observations(T)
        assert [(row.worker_id, row.generation) for row in rows] == [
            ("worker-1", "pf_" + "b" * 24)
        ]
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
                   cost_limit_micros=1000, hard_stop=True, window="daily")
        )
        await k.cost.reserve(T, ["dept:eng"], tokens=0, micros=900)
        with pytest.raises(BudgetExceeded):
            await k.cost.reserve(T, ["dept:eng"], tokens=0, micros=200)
    finally:
        await store.close()


@_pg
async def test_pg_durability_across_reconnect():
    """A work item written, then read after a fresh connection (a restart)."""
    from boltrig.store import PostgresStore

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
    from boltrig.config import apply_manifest, load_manifest

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
    from boltrig.adapters.builtin.memory_tickets import build as build_tickets
    from boltrig.store import PostgresStore

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


class _ReleaseOnConflict:
    """Connection proxy that commits an idempotency_release from an independent
    connection the instant a claim's INSERT conflicts - i.e. exactly in the window
    between the ON CONFLICT DO NOTHING and the FOR UPDATE re-read."""

    def __init__(self, conn, release):
        self._conn = conn
        self._release = release
        self.fired = False
        # The connection the release ran on. The race only exists because
        # idempotency_release re-enters with_tenant and so takes a SECOND pooled
        # connection; if with_tenant ever becomes nesting-aware and hands back the
        # caller's, the DELETE would join this transaction, the re-read would still
        # find nothing, and this test would keep passing while proving nothing.
        self.release_conn_id: int | None = None

    def __getattr__(self, name):
        return getattr(self._conn, name)

    async def fetchrow(self, query, *args):
        row = await self._conn.fetchrow(query, *args)
        if not self.fired and row is None and query.lstrip().startswith("INSERT"):
            self.fired = True
            await self._release()
        return row


@_pg
@pytest.mark.store
@pytest.mark.invariant("SEC-15")
async def test_claim_survives_a_release_between_the_insert_and_the_reread():
    """A key released mid-claim is re-acquired, not read back as a vanished row.

    ON CONFLICT DO NOTHING takes no lock on the row it conflicted with, so under
    READ COMMITTED a concurrent release (dispatch takes one whenever a gate rejects
    before start) can commit between the INSERT and the FOR UPDATE re-read, which
    then matches nothing. The key is free at that point, so Postgres must answer
    ACQUIRED like the in-memory twin does instead of raising on a None row.
    """
    store = await _fresh_pg()
    try:
        args = dict(
            actor="agent",
            on_behalf_of=None,
            workspace_id=None,
            noun="ticket",
            verb="ticket.create",
            request_hash="request",
            lease_seconds=60,
        )
        held = await store.idempotency_claim(T, "k", owner_token="owner-1", **args)
        assert held.status == IdempotencyClaimStatus.ACQUIRED
        released: list[bool] = []
        real_with_tenant = store.with_tenant
        proxies: list[_ReleaseOnConflict] = []

        @contextlib.asynccontextmanager
        async def racing(tenant_id):
            proxy: _ReleaseOnConflict | None = None

            async def release():
                async with real_with_tenant(tenant_id) as other:
                    if proxy is not None:
                        proxy.release_conn_id = id(other)
                released.append(await store.idempotency_release(T, "k", "owner-1"))

            async with real_with_tenant(tenant_id) as conn:
                proxy = _ReleaseOnConflict(conn, release)
                proxies.append(proxy)
                yield proxy

        store.with_tenant = racing
        try:
            claim = await store.idempotency_claim(T, "k", owner_token="owner-2", **args)
        finally:
            # del, not reassign: assigning the bound method back leaves a permanent
            # instance attribute holding a reference cycle instead of unshadowing.
            del store.with_tenant
        assert released == [True]  # the release really did commit inside the window
        racer = next(p for p in proxies if p.fired)
        assert racer.release_conn_id is not None and racer.release_conn_id != id(racer._conn), (
            "the release ran on the claim's own connection, so this no longer "
            "reproduces the cross-connection race it exists to pin"
        )
        assert claim.status == IdempotencyClaimStatus.ACQUIRED, (
            "a key released between the INSERT and the FOR UPDATE re-read must be "
            "re-acquired, not read back as a vanished row"
        )
    finally:
        await store.close()
