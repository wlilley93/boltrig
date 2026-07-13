"""Alembic/bootstrap parity against a real PostgreSQL catalogue (FR-OPS-01)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit
import uuid

import asyncpg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from boltrig.api.readiness import EXPECTED_ALEMBIC_HEAD
from boltrig.store.postgres import PostgresStore, normalize_dsn

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "migrations" / "baseline.sql"
RLS = ROOT / "boltrig" / "store" / "rls.sql"
BASELINE_SHA256 = "eef6f12d1c1a6b754f3aab5aa70ed73e7c168d98322f6b94be51c3e2565b0eef"

pytestmark = pytest.mark.store


@pytest.mark.invariant("FR-OPS-01")
def test_alembic_baseline_is_immutable() -> None:
    """Old revisions never read the mutable convenience bootstrap."""
    assert hashlib.sha256(BASELINE.read_bytes()).hexdigest() == BASELINE_SHA256
    revision = (ROOT / "migrations" / "versions" / "0001_baseline.py").read_text()
    assert 'parents[1] / "baseline.sql"' in revision
    assert '"boltrig" / "store" / "schema.sql"' not in revision


@pytest.mark.invariant("FR-OPS-03")
def test_packaged_readiness_head_matches_alembic_head() -> None:
    """The image-safe readiness constant cannot drift from the revision graph."""
    config = Config(str(ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_current_head() == EXPECTED_ALEMBIC_HEAD


def _database_url() -> str:
    value = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
    if not value:
        pytest.skip("BOLTRIG_TEST_DATABASE_URL not set")
    return normalize_dsn(value)


def _offline_migration_sql() -> str:
    env = os.environ.copy()
    env["DATABASE_URL"] = "postgresql://offline:offline@localhost/offline"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _run_alembic(database_url: str, revision: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _with_database(database_url: str, database: str) -> str:
    parts = urlsplit(database_url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", parts.query, parts.fragment))


_CATALOGUE_QUERIES = {
    "tables": """
        SELECT c.relname, c.relkind
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = $1 AND c.relkind IN ('r', 'p')
          AND c.relname <> 'alembic_version'
        ORDER BY 1, 2
    """,
    "columns": """
        SELECT c.relname, a.attname,
               pg_catalog.format_type(a.atttypid, a.atttypmod),
               a.attnotnull,
               COALESCE(pg_get_expr(d.adbin, d.adrelid), '')
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
        WHERE n.nspname = $1 AND c.relkind IN ('r', 'p')
          AND c.relname <> 'alembic_version'
          AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY 1, 2
    """,
    "constraints": """
        SELECT c.relname, x.conname, x.contype, pg_get_constraintdef(x.oid, true)
        FROM pg_constraint x
        JOIN pg_class c ON c.oid = x.conrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = $1 AND c.relname <> 'alembic_version'
        ORDER BY 1, 2
    """,
    "indexes": """
        SELECT tablename, indexname, indexdef
        FROM pg_indexes
        WHERE schemaname = $1 AND tablename <> 'alembic_version'
        ORDER BY 1, 2
    """,
    "sequences": """
        SELECT sequence_name, data_type, start_value, minimum_value,
               maximum_value, increment
        FROM information_schema.sequences
        WHERE sequence_schema = $1
        ORDER BY 1
    """,
}


def _normalise(value: object, schema: str) -> object:
    if not isinstance(value, str):
        return value
    return value.replace(f'"{schema}".', '"<schema>".').replace(
        f"{schema}.", "<schema>."
    )


async def _catalogue(conn: asyncpg.Connection, schema: str) -> dict[str, list[tuple]]:
    await conn.execute(f'SET search_path TO "{schema}", public')
    result: dict[str, list[tuple]] = {}
    for name, query in _CATALOGUE_QUERIES.items():
        rows = await conn.fetch(query, schema)
        result[name] = [tuple(_normalise(value, schema) for value in row) for row in rows]
    return result


async def _apply_in_schema(conn: asyncpg.Connection, schema: str, sql: str) -> None:
    await conn.execute(f'CREATE SCHEMA "{schema}"')
    await conn.execute(f'SET search_path TO "{schema}", public')
    await conn.execute(sql)


@pytest.mark.invariant("FR-OPS-01")
async def test_alembic_head_matches_bootstrap_schema() -> None:
    """Both supported fresh-database paths create the same semantic catalogue."""
    migrated = f"parity_migrated_{uuid.uuid4().hex}"
    bootstrap = f"parity_bootstrap_{uuid.uuid4().hex}"
    conn = await asyncpg.connect(_database_url())
    try:
        # Extensions are database-wide, not schema-local. Install vector in its
        # production schema before isolating the two table catalogues.
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
        await _apply_in_schema(conn, migrated, _offline_migration_sql())
        await _apply_in_schema(
            conn, bootstrap, (ROOT / "boltrig" / "store" / "schema.sql").read_text()
        )
        migrated_catalogue = await _catalogue(conn, migrated)
        bootstrap_catalogue = await _catalogue(conn, bootstrap)
        for section in _CATALOGUE_QUERIES:
            migrated_rows = migrated_catalogue[section]
            bootstrap_rows = bootstrap_catalogue[section]
            assert migrated_rows == bootstrap_rows, (
                f"{section} differ\n"
                f"migration only: {sorted(set(migrated_rows) - set(bootstrap_rows))}\n"
                f"bootstrap only: {sorted(set(bootstrap_rows) - set(migrated_rows))}"
            )
    finally:
        await conn.execute("SET search_path TO public")
        await conn.execute(f'DROP SCHEMA IF EXISTS "{migrated}" CASCADE')
        await conn.execute(f'DROP SCHEMA IF EXISTS "{bootstrap}" CASCADE')
        await conn.close()


@pytest.mark.invariant("FR-OPS-01")
@pytest.mark.invariant("SEC-65")
@pytest.mark.invariant("FR-OPS-03")
async def test_data_bearing_rls_database_upgrades_from_previous_head() -> None:
    """0021 -> head preserves data and extends an existing FORCE-RLS fence."""
    source_url = _database_url()
    database = f"boltrig_upgrade_{uuid.uuid4().hex}"
    database_url = _with_database(source_url, database)
    admin = await asyncpg.connect(source_url)
    conn: asyncpg.Connection | None = None
    try:
        await admin.execute(f'CREATE DATABASE "{database}"')
        _run_alembic(database_url, "0021_work_items_run_lookup")
        conn = await asyncpg.connect(database_url)
        await conn.execute(
            """
            INSERT INTO users (tenant_id, id, email, groups)
            VALUES
                ('upgrade-a', 'null-groups', 'null@example.test', NULL),
                ('upgrade-a', 'two-groups', 'two@example.test', '["dev", "ops"]'::jsonb),
                ('upgrade-b', 'empty-groups', 'empty@example.test', '[]'::jsonb)
            """
        )
        await conn.execute(RLS.read_text(encoding="utf-8"))
        await conn.close()
        conn = None

        _run_alembic(database_url, "head")
        conn = await asyncpg.connect(database_url)
        rows = await conn.fetch("SELECT id, groups, role, source FROM users ORDER BY id")
        assert [(row["id"], row["groups"]) for row in rows] == [
            ("empty-groups", []),
            ("null-groups", []),
            ("two-groups", ["dev", "ops"]),
        ]
        assert {(row["role"], row["source"]) for row in rows} == {("none", "idp")}
        assert not await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'users'
                  AND column_name = 'updated_at'
            )
            """
        )

        scoped = [
            "channel_bindings",
            "channel_pairings",
            "memory_projection_statuses",
            "memory_vectors",
            "memory_vector_edges",
        ]
        policies = await conn.fetch(
            """
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, p.polname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_policy p ON p.polrelid = c.oid
            WHERE n.nspname = 'public' AND c.relname = ANY($1::text[])
            ORDER BY c.relname
            """,
            scoped,
        )
        assert [row["relname"] for row in policies] == sorted(scoped)
        assert all(row["relrowsecurity"] and row["relforcerowsecurity"] for row in policies)
        assert {row["polname"] for row in policies} == {"tenant_isolation"}
        assert await conn.fetchval("SELECT version_num FROM alembic_version") == (
            EXPECTED_ALEMBIC_HEAD
        )
        await conn.close()
        conn = None

        store = await PostgresStore.connect(database_url, apply_schema=False)
        try:
            assert await store.readiness_snapshot() == (
                True,
                (EXPECTED_ALEMBIC_HEAD,),
            )
        finally:
            await store.close()
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
