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
