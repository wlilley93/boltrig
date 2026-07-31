"""Postgres RLS: DB-enforced tenant isolation + a non-bypassing app role (SEC-65).

Runs only when BOLTRIG_TEST_DATABASE_URL points at a Postgres (CI provides one;
offline it skips cleanly, P9). It applies the opt-in RLS overlay (boltrig/store/
rls.sql), proves that:

  * FORCE RLS binds even the table owner - with app.tenant_id = A, only A's rows
    are visible;
  * the least-privilege boltrig_app role (NOBYPASSRLS) sees only its tenant, and a
    write into another tenant is rejected by the policy's WITH CHECK;
  * an unset app.tenant_id yields ZERO rows (fail-closed), never wide-open;

then tears RLS back down so it cannot contaminate the other Postgres tests sharing
the database. `nouns` is the probe table (only id + tenant_id are NOT NULL).
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import asyncpg
import pytest

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
_pg = pytest.mark.skipif(not DSN, reason="set BOLTRIG_TEST_DATABASE_URL for RLS tests")

# Same tenant-scoped table list rls.sql enables; the teardown disables them all so
# the owner-connected default path (and the other PG tests) keep working afterwards.
_SCOPED = (
    "nouns,verbs,verb_bindings,adapters,skills,agent_capabilities,workflow_definitions,"
    "model_endpoints,work_items,hitl_requests,hitl_responses,users,role_mappings,audit_log,"
    "idempotency_keys,budgets,credential_refs,tenant_permissions,conversations,config_revisions,"
    "eval_cases,eval_runs,notification_prefs,personal_agents,memory_items,mcp_servers,"
    "mcp_probe_receipts,conversation_messages,user_invitations,user_settings,user_sessions,memory_facts,"
    "memory_ingestions,memory_erasures,memory_projection_statuses,"
    "memory_vectors,memory_vector_edges,knowledge_uploads,knowledge_blobs,knowledge_assets,"
    "knowledge_source_occurrences,knowledge_revisions,knowledge_representations,"
    "knowledge_segments,knowledge_embeddings,knowledge_asset_access,knowledge_providers,"
    "knowledge_projection_statuses,knowledge_jobs,knowledge_projection_outbox"
).split(",")

_DISABLE_RLS = (
    "DO $$ DECLARE t text; scoped text[] := ARRAY[%s]; BEGIN "
    "FOREACH t IN ARRAY scoped LOOP "
    "  IF EXISTS (SELECT 1 FROM information_schema.tables "
    "             WHERE table_schema='public' AND table_name=t) THEN "
    "    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %%I', t); "
    "    EXECUTE format('ALTER TABLE %%I NO FORCE ROW LEVEL SECURITY', t); "
    "    EXECUTE format('ALTER TABLE %%I DISABLE ROW LEVEL SECURITY', t); "
    "  END IF; END LOOP; END $$;"
) % ",".join("'%s'" % t for t in _SCOPED)


@_pg
@pytest.mark.invariant("SEC-65")
def test_rls_enforces_tenant_isolation_and_fails_closed():
    async def run():
        from boltrig.store.postgres import PostgresStore

        store = await PostgresStore.connect(DSN)
        pool = store._pool
        try:
            await store.apply_rls()  # idempotent; the artifact under test

            # seed two tenants (owner is FORCE-bound, so set the GUC per write)
            async with pool.acquire() as c:
                async with c.transaction():
                    await c.execute("SELECT set_config('app.tenant_id','rls_A',true)")
                    await c.execute(
                        "INSERT INTO nouns (id, tenant_id) VALUES ('rls_n_a','rls_A') "
                        "ON CONFLICT DO NOTHING"
                    )
                async with c.transaction():
                    await c.execute("SELECT set_config('app.tenant_id','rls_B',true)")
                    await c.execute(
                        "INSERT INTO nouns (id, tenant_id) VALUES ('rls_n_b','rls_B') "
                        "ON CONFLICT DO NOTHING"
                    )

                # FORCE binds the owner: scoped to A, every visible row is A's.
                # A SUPERUSER connection bypasses RLS unconditionally (documented
                # Postgres behaviour; FORCE only binds a non-superuser owner), so
                # this owner-only assertion is meaningful only off a superuser DSN.
                # The substantive proof below runs as the NOBYPASSRLS boltrig_app
                # role, which binds regardless of the connecting user's superuser
                # bit, so RLS is always exercised.
                is_super = await c.fetchval(
                    "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
                )
                async with c.transaction():
                    await c.execute("SELECT set_config('app.tenant_id','rls_A',true)")
                    rows = await c.fetch("SELECT tenant_id FROM nouns")
                    if not is_super:
                        assert rows and all(r["tenant_id"] == "rls_A" for r in rows)

                # the least-privilege role: sees only its tenant
                async with c.transaction():
                    await c.execute("SET LOCAL ROLE boltrig_app")
                    await c.execute("SELECT set_config('app.tenant_id','rls_A',true)")
                    rows = await c.fetch("SELECT tenant_id FROM nouns")
                    assert rows and all(r["tenant_id"] == "rls_A" for r in rows)

                # WITH CHECK: it cannot write a row into another tenant
                with pytest.raises(asyncpg.PostgresError):
                    async with c.transaction():
                        await c.execute("SET LOCAL ROLE boltrig_app")
                        await c.execute("SELECT set_config('app.tenant_id','rls_A',true)")
                        await c.execute(
                            "INSERT INTO nouns (id, tenant_id) VALUES ('rls_cross','rls_B')"
                        )

                # fail-closed: an unset GUC yields zero rows (never wide-open)
                async with c.transaction():
                    await c.execute("SET LOCAL ROLE boltrig_app")
                    count = await c.fetchval("SELECT count(*) FROM nouns")
                    assert count == 0
        finally:
            # restore the DB for the owner-connected default path + other PG tests
            async with pool.acquire() as c:
                await c.execute(_DISABLE_RLS)
                await c.execute("DELETE FROM nouns WHERE id IN ('rls_n_a','rls_n_b','rls_cross')")
            await store.close()

    asyncio.run(run())


@_pg
@pytest.mark.invariant("SEC-65")
def test_rls_binds_the_STORE_not_just_a_hand_rolled_connection():
    """The deployed shape: does a store call through _RlsPool actually get fenced?

    THE TEST ABOVE PASSES ON AN UNPROTECTED DEPLOYMENT, and that is why this one
    exists. It issues `SET LOCAL ROLE boltrig_app` itself before asserting, and it
    skips its owner-side assertion when the connecting user is a superuser. Both are
    reasonable in isolation and together they mean it proves the POLICIES are correct
    while proving nothing about the APP.

    Measured on the beelink 2026-07-30 with the overlay applied and
    relrowsecurity + relforcerowsecurity TRUE on every tenant table: the app,
    connected as the owner, could still read every tenant's rows, because the owner
    is a superuser and a superuser bypasses RLS unconditionally. The fence was up and
    the application walked round it.

    So this test does NOT touch roles. It binds a tenant the way the API does
    (set_current_tenant) and then goes through the store's ordinary fetch path. If
    the store stops assuming boltrig_app, this fails.
    """
    async def run():
        from boltrig.store.postgres import PostgresStore, set_current_tenant

        owner = await PostgresStore.connect(DSN)
        try:
            await owner.apply_rls()
            async with owner._pool.acquire() as c:
                for tid, nid in (("rls_A", "rls_store_a"), ("rls_B", "rls_store_b")):
                    async with c.transaction():
                        await c.execute("SELECT set_config('app.tenant_id',$1,true)", tid)
                        await c.execute(
                            "INSERT INTO nouns (id, tenant_id) VALUES ($1,$2) "
                            "ON CONFLICT DO NOTHING", nid, tid,
                        )

            # the deployed configuration: rls=True, apply_schema=False
            store = await PostgresStore.connect(DSN, apply_schema=False, rls=True)
            try:
                # The overlay is applied, so the role must have been found. If this is
                # False the rest of the test would pass vacuously against an
                # unprotected store, so it is asserted rather than assumed.
                assert store._assume_app_role is True, (
                    "boltrig_app not found after apply_rls; the assertions below would "
                    "then be testing an unprotected store and passing"
                )

                set_current_tenant("rls_A")
                rows = await store._pool.fetch(
                    "SELECT id FROM nouns WHERE id IN ('rls_store_a','rls_store_b')"
                )
                ids = {r["id"] for r in rows}
                assert "rls_store_a" in ids, "tenant A cannot see its own row"
                assert "rls_store_b" not in ids, (
                    "TENANT B'S ROW WAS VISIBLE TO TENANT A through the store. The "
                    "policies are applied but the app is bypassing them - it is "
                    "connected as a superuser and never dropped to boltrig_app."
                )

                # fail-closed: no tenant bound at all yields nothing, never everything
                set_current_tenant(None)
                none_rows = await store._pool.fetch(
                    "SELECT id FROM nouns WHERE id IN ('rls_store_a','rls_store_b')"
                )
                assert none_rows == [], f"unbound tenant saw {len(none_rows)} rows"

                # with_tenant is a SECOND path - it opens its own transaction and so
                # never reaches _scoped. It was unprotected while _scoped was fenced.
                async with store.with_tenant("rls_A") as conn:
                    via = await conn.fetch(
                        "SELECT id FROM nouns WHERE id IN ('rls_store_a','rls_store_b')"
                    )
                assert {r["id"] for r in via} == {"rls_store_a"}, (
                    "with_tenant did not fence the connection"
                )
            finally:
                set_current_tenant(None)
                await store.close()
        finally:
            async with owner._pool.acquire() as c:
                await c.execute(_DISABLE_RLS)
                await c.execute(
                    "DELETE FROM nouns WHERE id IN ('rls_store_a','rls_store_b')"
                )
            await owner.close()

    asyncio.run(run())


@_pg
@pytest.mark.invariant("SEC-65")
def test_the_control_plane_enumeration_still_sees_tenants_UNDER_rls():
    """The 2026-07-31 outage, reproduced: the fence blinded the janitors.

    ``run_anchor_sweep_detailed`` and ``run_hitl_expiry_sweep`` both begin with
    ``store.list_orgs()``. It has no tenant to bind - it is the query that
    DISCOVERS the tenants - so under the fence it ran unbound, the organisations
    policy ``id = current_setting('app.tenant_id', true)`` matched nothing, and it
    returned ZERO rows on a deployment that had a tenant.

    Both sweeps then iterated an empty list, did nothing, wrote no receipt and
    logged nothing, so overdue HITL approvals stopped timing out (SEC-14) and
    audit-chain anchoring stopped (COUNTY 9 D4) for nine hours while both loops
    presented as idle.

    Nothing raised and nothing could. Only an assertion that the enumeration
    RETURNS SOMETHING catches it, which is why this test asserts on the count and
    not on an absence of errors.
    """
    async def run():
        from boltrig.models.tenancy import Organisation
        from boltrig.store.postgres import PostgresStore

        owner = await PostgresStore.connect(DSN)
        try:
            await owner.apply_rls()
            await owner.create_org(
                Organisation(id="rls_cp_org", name="rls cp", slug="rls-cp")
            )
        finally:
            await owner.close()

        # rls=True is the deployed posture: every fenced call drops to the
        # NOBYPASSRLS boltrig_app role, so the policies actually bind.
        store = await PostgresStore.connect(DSN, apply_schema=False, rls=True)
        try:
            assert store._assume_app_role, (
                "rls.sql must be applied for this to prove anything; without the "
                "role switch the policies do nothing and the test cannot fail"
            )
            orgs = await store.list_orgs()
            assert any(o.id == "rls_cp_org" for o in orgs), (
                "list_orgs returned no tenants under RLS, so every janitor that "
                "sweeps it does nothing at all and reports itself idle"
            )

            # The contrast that shows the fence is still ON for ordinary reads:
            # a tenant-scoped read with no tenant bound must still see nothing.
            async with store._pool.acquire() as c:
                async with c.transaction():
                    await c.execute("SET LOCAL ROLE boltrig_app")
                    assert await c.fetchval("SELECT count(*) FROM nouns") == 0, (
                        "the exemption must be narrow: unbound tenant-scoped reads "
                        "must stay fail-closed"
                    )
        finally:
            await store.close()
            cleanup = await PostgresStore.connect(DSN, apply_schema=False)
            try:
                async with cleanup._pool.acquire() as c:
                    await c.execute(_DISABLE_RLS)
                    await c.execute(
                        "ALTER TABLE organisations NO FORCE ROW LEVEL SECURITY"
                    )
                    await c.execute(
                        "ALTER TABLE organisations DISABLE ROW LEVEL SECURITY"
                    )
                    await c.execute("DELETE FROM organisations WHERE id='rls_cp_org'")
            finally:
                await cleanup.close()

    asyncio.run(run())


@_pg
@pytest.mark.invariant("SEC-65")
def test_an_explicit_transaction_is_fenced_AND_still_works_under_rls():
    """The other half of the 2026-07-31 fence audit, and the risk in fixing it.

    22 sites held their own transaction, set ``app.tenant_id`` and never switched
    role. Since the app connects as a SUPERUSER owner, and a superuser bypasses RLS
    even under FORCE, those transactions were not fenced at all - five of them
    carrying the comment "RLS-live: scope this explicit transaction".

    Adding the switch is not free: it makes writes that previously bypassed the
    policies subject to them. The whole suite runs with RLS OFF, so it cannot tell
    the difference between a write that satisfies a policy and one that never met
    it. This is the test that can.

    ``record_background_job_attempt``/``list_background_job_receipts`` are the pair
    /readyz depends on, and ``background_job_receipts`` IS in the rls.sql scoped
    list, so it has a real policy to satisfy.
    """
    async def run():
        from boltrig.models.tenancy import Organisation
        from boltrig.observability.background_jobs import (
            new_background_process_identity,
        )
        from boltrig.store.postgres import PostgresStore

        identity = new_background_process_identity()
        owner = await PostgresStore.connect(DSN)
        try:
            await owner.apply_rls()
            for tid in ("rls_tx_a", "rls_tx_b"):
                await owner.create_org(
                    Organisation(id=tid, name=tid, slug=tid.replace("_", "-"))
                )
        finally:
            await owner.close()

        store = await PostgresStore.connect(DSN, apply_schema=False, rls=True)
        try:
            assert store._assume_app_role, "without the role switch this proves nothing"

            # The write must still SUCCEED with the policy in force. If the role
            # switch had been added without the GUC, or with the wrong tenant, this
            # is where it would fail - and it would fail in production, not here.
            # BOTH tenants get a row. Without tenant B's row the fencing assertion
            # below is vacuous: a full-table scan of a table containing one tenant
            # sees one tenant whether or not any policy applies. An earlier draft
            # seeded only A and passed with the role switch deleted.
            for tid in ("rls_tx_a", "rls_tx_b"):
                receipt = await store.record_background_job_attempt(
                    tenant_id=tid,
                    job_name="retention",
                    process_instance_identity=identity,
                    interval_seconds=60.0,
                    attempted_at=datetime.now(timezone.utc),
                    succeeded=True,
                    item_count=1,
                )
                assert receipt.tenant_id == tid

            assert await store.list_background_job_receipts("rls_tx_a")

            # And the transaction must be FENCED. This is the half that is easy to
            # get wrong: asserting that list_background_job_receipts("rls_tx_b")
            # comes back empty proves NOTHING, because that method carries its own
            # WHERE tenant_id=$1 and returns [] whether or not a policy exists. A
            # first draft of this test did exactly that and passed with the role
            # switch deleted.
            #
            # Only a query with NO tenant predicate can see the policy at all. It
            # must run through the same helper the converted methods use, so the
            # thing under test is the binding, not a hand-rolled imitation of it.
            from boltrig.store.tenant_scope import bind_conn_to_tenant

            async with store._pool.acquire() as conn:
                async with conn.transaction():
                    await bind_conn_to_tenant(conn, "rls_tx_a", pool=store._pool)
                    seen = await conn.fetch(
                        "SELECT tenant_id FROM background_job_receipts"
                    )
            assert seen, "the bound tenant must still see its own rows"
            assert {r["tenant_id"] for r in seen} == {"rls_tx_a"}, (
                "an unpredicated read inside a bound explicit transaction saw "
                f"other tenants: {sorted({r['tenant_id'] for r in seen})}. The "
                "transaction is not subject to the policy - which is what setting "
                "the GUC without SET LOCAL ROLE looks like under a superuser owner."
            )
        finally:
            await store.close()
            cleanup = await PostgresStore.connect(DSN, apply_schema=False)
            try:
                async with cleanup._pool.acquire() as c:
                    await c.execute(_DISABLE_RLS)
                    await c.execute(
                        "ALTER TABLE organisations NO FORCE ROW LEVEL SECURITY"
                    )
                    await c.execute(
                        "ALTER TABLE organisations DISABLE ROW LEVEL SECURITY"
                    )
                    await c.execute(
                        "DELETE FROM background_job_receipts "
                        "WHERE tenant_id IN ('rls_tx_a','rls_tx_b')"
                    )
                    await c.execute(
                        "DELETE FROM organisations WHERE id IN ('rls_tx_a','rls_tx_b')"
                    )
            finally:
                await cleanup.close()

    asyncio.run(run())
