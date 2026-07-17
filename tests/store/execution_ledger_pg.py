"""Shared real-PostgreSQL fixtures for the durable execution-ledger tests.

Runs only when BOLTRIG_TEST_DATABASE_URL points at a Postgres (CI provides a
service; offline the tests skip cleanly, P9). The DDL is collected by executing
the shipped migrations' own upgrade bodies rather than a copy pasted into a test,
so the adapter is always exercised against the schema that actually ships and the
fixture cannot silently drift away from it.
"""

from __future__ import annotations

import importlib.util
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace

import asyncpg
import pytest

from boltrig.fleet.infrastructure.postgres_execution_ledger import PostgresExecutionLedger

from tests.unit.execution_ledger_fixtures import CLOCK_NOW

ROOT = Path(__file__).resolve().parents[2]
DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
pg_only = pytest.mark.skipif(
    not DSN, reason="set BOLTRIG_TEST_DATABASE_URL for Postgres tests"
)

TABLES = (
    "execution_root_runs",
    "execution_phases",
    "execution_work_items",
    "execution_assignments",
    "execution_results",
    "execution_verifications",
    "execution_commands",
    "execution_events",
    "execution_outbox",
    "runtime_identities",
    "codex_thread_bindings",
    "codex_turn_bindings",
    "codex_item_bindings",
)
TRUNCATE = f"TRUNCATE {', '.join(TABLES)}"


async def init_codec(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


def migration_sql(revision: str) -> list[str]:
    """Collect one shipped migration's own statements by running its upgrade body."""

    path = ROOT / "migrations" / "versions" / f"{revision}.py"
    spec = importlib.util.spec_from_file_location(f"boltrig_migration_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    statements: list[str] = []
    module.op = SimpleNamespace(execute=statements.append)  # type: ignore[attr-defined]
    module.upgrade()
    return statements


def ddl() -> str:
    """The execution-ledger schema as shipped: 0026 as created, 0031 as amended."""

    return ";\n".join(
        migration_sql("0026_execution_ledger")
        + migration_sql("0031_execution_ledger_fidelity")
    )


@pytest.fixture
async def ledger_pool() -> AsyncIterator[asyncpg.Pool]:
    # Function-scoped on purpose: asyncio_mode = "auto" gives each test its own
    # event loop, and a module-scoped asyncpg pool would bind to the first one.
    # max_size >= 8 so the concurrent compare-and-swap assert genuinely races two
    # connections on the advisory lock rather than queueing on one, and so the
    # lock-order proof contends on real backends rather than on the pool queue.
    pool = await asyncpg.create_pool(dsn=DSN, min_size=2, max_size=8, init=init_codec)
    assert pool is not None
    async with pool.acquire() as conn:
        await conn.execute(ddl())
        await conn.execute(TRUNCATE)
    yield pool
    await pool.close()


@pytest.fixture
def ledger(ledger_pool: asyncpg.Pool) -> PostgresExecutionLedger:
    return PostgresExecutionLedger(ledger_pool, clock=lambda: CLOCK_NOW)


__all__ = [
    "DSN",
    "TABLES",
    "TRUNCATE",
    "ddl",
    "init_codec",
    "ledger",
    "ledger_pool",
    "migration_sql",
    "pg_only",
]
