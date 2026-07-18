"""RLS fence-coverage drift guard (SEC-08 / K-22 / SEC-65).

The RLS overlay (``boltrig/store/rls.sql``) fences a hand-maintained list of
tenant-scoped tables. A hand-maintained list drifts: migrations 0026-0032 added
26 tenant_id-bearing tables and every one landed OUTSIDE that list, so an
RLS-enabled deployment left them without a database-level tenant fence and
nothing caught it.

This test is the guard against the next one. Against a real Postgres it builds a
throwaway catalogue from ``schema.sql`` with the opt-in RLS overlay applied, then
enumerates EVERY table that actually carries a ``tenant_id`` column and asserts
each is EITHER RLS-fenced (``relforcerowsecurity`` true plus a ``tenant_isolation``
policy in ``pg_policy``) OR in :data:`DOCUMENTED_RLS_EXCLUSIONS`. It FAILS the
moment a future tenant table lands unfenced and unexcused.

Real Postgres only: it reads ``pg_policy`` / ``pg_class`` and so cannot run on the
in-memory store. DSN-gated (skips cleanly offline, e.g. ``make check``) and RUNS
under ``scripts/with_test_postgres.sh``. It works on a fresh throwaway database so
it never depends on, or contaminates, the shared test catalogue, and so it needs
no hand-maintained teardown list (the very thing whose drift it exists to catch).
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest

from boltrig.store.postgres import normalize_dsn

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "boltrig" / "store" / "schema.sql"
RLS = ROOT / "boltrig" / "store" / "rls.sql"

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
_pg = pytest.mark.skipif(
    not DSN, reason="set BOLTRIG_TEST_DATABASE_URL for the RLS fence drift guard"
)

# THE source of truth for tables allowed to carry a tenant_id WITHOUT a database
# RLS fence. Each is resolved by an unguessable key BEFORE any tenant is bound, so
# a `tenant_id = app.tenant_id` policy would fail-closed to ZERO rows under the
# unset GUC and break that pre-tenant lookup; each keeps its own SQL-level guard.
# These match the DELIBERATELY EXCLUDED block in boltrig/store/rls.sql. Adding a
# table here MUST be a deliberate one-line act with a comment stating why the row
# is resolved before the tenant is known - it is the ONLY sanctioned escape from
# the fence, so it is meant to be uncomfortable to grow.
DOCUMENTED_RLS_EXCLUSIONS = frozenset(
    {
        # PAT authentication resolves a token by its hash before the tenant is
        # known (a legitimate cross-tenant read).
        "personal_access_tokens",
        # The pre-tenant email -> orgs index: login/org-switch resolves it by the
        # normalised email BEFORE any tenant is bound ([2026] VJS-COUNTY 11, D1).
        "identity_orgs",
        # The inbound webhook path resolves the channel (and hence the tenant) by
        # its unguessable id BEFORE the tenant is bound (decision 0003):
        # get_channel_by_id -> set_current_tenant, in that order.
        "channels",
    }
)


def _with_database(url: str, database: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", parts.query, parts.fragment))


@_pg
@pytest.mark.invariant("SEC-169")
async def test_every_tenant_table_is_rls_fenced_or_documented_excluded() -> None:
    source_url = normalize_dsn(DSN or "")
    database = f"boltrig_rls_fence_{uuid.uuid4().hex}"
    admin = await asyncpg.connect(source_url)
    conn: asyncpg.Connection | None = None
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
        conn = await asyncpg.connect(_with_database(source_url, database))
        # schema.sql declares vector columns; the extension must exist first.
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.execute(SCHEMA.read_text(encoding="utf-8"))
        await conn.execute(RLS.read_text(encoding="utf-8"))

        # Every table that actually carries a tenant_id column (the ground truth,
        # read from the live catalogue, not any hand-kept list).
        tenant_tables = {
            r["table_name"]
            for r in await conn.fetch(
                """SELECT DISTINCT table_name FROM information_schema.columns
                   WHERE table_schema = 'public' AND column_name = 'tenant_id'"""
            )
        }
        assert tenant_tables, "expected schema.sql to define tenant_id-bearing tables"

        # Tables the overlay actually fenced: FORCE row security AND a
        # tenant_isolation policy present (the id-keyed organisations policy has no
        # tenant_id column, so it never appears in tenant_tables and is out of
        # scope here - it is covered by SEC-105).
        fenced = {
            r["relname"]
            for r in await conn.fetch(
                """SELECT c.relname
                   FROM pg_class c
                   JOIN pg_namespace n ON n.oid = c.relnamespace
                   JOIN pg_policy p ON p.polrelid = c.oid
                   WHERE n.nspname = 'public'
                     AND c.relforcerowsecurity
                     AND p.polname = 'tenant_isolation'"""
            )
        }

        # A stale exclusion is itself a bug: every excused name must be a real
        # tenant table, or the exclusion is dead and hides nothing.
        dead_exclusions = sorted(DOCUMENTED_RLS_EXCLUSIONS - tenant_tables)
        assert not dead_exclusions, (
            "DOCUMENTED_RLS_EXCLUSIONS names tables with no tenant_id column "
            f"(dead/typo, remove them): {dead_exclusions}"
        )

        # The guard: a tenant table must be fenced or explicitly, documentedly
        # excused. Anything else is an unfenced tenant table - fail, naming it.
        unfenced = sorted(
            t for t in tenant_tables if t not in fenced and t not in DOCUMENTED_RLS_EXCLUSIONS
        )
        assert not unfenced, (
            "tenant_id-bearing tables with NO database RLS fence and NOT in the "
            f"documented exclusion set: {unfenced}. Add each to the `scoped` array "
            "in boltrig/store/rls.sql, or - ONLY if the row is resolved before a "
            "tenant is bound - add it to DOCUMENTED_RLS_EXCLUSIONS with a comment "
            "citing the pre-tenant-resolution reason (see personal_access_tokens)."
        )
    finally:
        if conn is not None:
            await conn.close()
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            database,
        )
        await admin.execute(f'DROP DATABASE IF EXISTS "{database}"')
        await admin.close()
