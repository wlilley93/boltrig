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


def _load_migration(path: Path) -> object:
    """Import one shipped migration module without running its upgrade body."""

    spec = importlib.util.spec_from_file_location(f"boltrig_migration_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def migration_sql(revision: str) -> list[str]:
    """Collect one shipped migration's own statements by running its upgrade body."""

    module = _load_migration(ROOT / "migrations" / "versions" / f"{revision}.py")
    statements: list[str] = []
    module.op = SimpleNamespace(execute=statements.append)  # type: ignore[attr-defined]
    module.upgrade()  # type: ignore[attr-defined]
    return statements


def _revision_chain() -> list[str]:
    """Order every shipped migration by its own ``down_revision`` links.

    Reading the chain rather than listing it is the point. A hand-maintained list
    omits each new migration by default and only a human notices, which is exactly
    how 0032 shipped with its own round-trip test red: `make check` is offline and
    skips this whole leg, so nothing else was watching.
    """

    versions = ROOT / "migrations" / "versions"
    down_of: dict[str, str | None] = {}
    for path in sorted(versions.glob("[0-9]*.py")):
        module = _load_migration(path)
        down_of[str(module.revision)] = module.down_revision
    ordered: list[str] = []
    by_down = {down: rev for rev, down in down_of.items()}
    current: str | None = None
    while (nxt := by_down.get(current)) is not None:
        ordered.append(nxt)
        current = nxt
    assert len(ordered) == len(down_of), "migration chain is broken or forked"
    return ordered


def ddl() -> str:
    """The schema exactly as a deployment builds it: the WHOLE chain, in order.

    Every shipped migration is executed in revision order, derived from the chain
    rather than listed here, so a new migration is included the moment it ships
    and this fixture cannot drift behind the schema it claims to prove the adapter
    against.

    It used to start at the ledger's own creating migration (0026) on the
    reasonable-sounding grounds that earlier ones build tables the ledger does not
    use. They do - but later ones do not confine themselves to ledger tables:
    0035_channel_durability alters `channels`, created back at 0019, so replaying
    0026..head against an empty database raises `relation "channels" does not
    exist` and every test in this file errors in setup.

    That was invisible for two reasons at once. A long-lived local test database
    already had `channels` from earlier full-chain runs, and in CI the outcome
    depended on whether test_migration_parity.py (which applies the whole chain)
    happened to be ordered first - so the suite was green until pytest-randomly
    dealt a different order. A partial replay is not "as a deployment builds it"
    in any case; a deployment runs the chain from the beginning, and so does this.
    """

    # Alembic creates its own bookkeeping table before it runs the first
    # migration, so a deployment always has it and 0015 can widen it unguarded.
    # This fixture replays the migrations' SQL directly, with no alembic in the
    # loop, so it has to stand that precondition up itself - as alembic builds it,
    # VARCHAR(32), which 0015 then widens to 64 exactly as it does in production.
    statements: list[str] = [
        "CREATE TABLE IF NOT EXISTS alembic_version ("
        "version_num VARCHAR(32) NOT NULL, "
        "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
    ]
    for revision in _revision_chain():
        statements.extend(migration_sql(revision))
    return ";\n".join(statements)


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
