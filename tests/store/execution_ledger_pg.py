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
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
import uuid

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


@asynccontextmanager
async def isolated_pool(
    *, min_size: int, max_size: int
) -> AsyncIterator[asyncpg.Pool]:
    """Give one fixture a fresh schema while replaying the real migration chain.

    ``ddl()`` intentionally contains unguarded CREATE statements where the
    shipped migration does. Replaying that exact chain into a long-lived shared
    schema makes test order decide whether setup succeeds. A unique schema keeps
    those statements meaningful: every fixture still proves a clean deployment
    build, and teardown removes its whole catalogue without weakening migrations
    into test-only idempotent variants.
    """

    assert DSN is not None
    schema = f"ledger_test_{uuid.uuid4().hex}"
    admin = await asyncpg.connect(dsn=DSN)
    try:
        await admin.execute(f'CREATE SCHEMA "{schema}"')
    finally:
        await admin.close()

    async def setup_isolated(conn: asyncpg.Connection) -> None:
        # asyncpg resets session settings when a connection returns to the pool,
        # so search_path belongs in ``setup`` (every checkout), not ``init``
        # (once per physical connection).
        await conn.execute(f'SET search_path TO "{schema}", public')

    pool: asyncpg.Pool | None = None
    try:
        pool = await asyncpg.create_pool(
            dsn=DSN, min_size=min_size, max_size=max_size,
            init=init_codec, setup=setup_isolated,
        )
        assert pool is not None
        yield pool
    finally:
        if pool is not None:
            await pool.close()
        admin = await asyncpg.connect(dsn=DSN)
        try:
            await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        finally:
            await admin.close()


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

    THE CHAIN IS A DAG, NOT A LINE, and this used to assume otherwise. It walked
    ``{down_revision: revision}`` from ``None``, which silently cannot represent
    two things Alembic allows and this repo now contains: two revisions sharing a
    parent (the dict keeps only the last one, so a whole branch vanishes), and a
    merge revision whose ``down_revision`` is a TUPLE of both heads (never equal
    to the string being looked up, so the walk simply stops). Both showed up the
    moment the capability and scoped-integration lines were merged at
    0081_merge_capability_and_integration_scope, and the failure was
    indistinguishable from a genuinely broken chain.

    So it is a topological sort now, tie-broken by revision id, which is the order
    Alembic itself would apply. The assertions still catch what the old walk was
    there to catch: a cycle or an orphan leaves revisions unemitted, and a fork
    that never rejoins leaves more than one head.
    """

    versions = ROOT / "migrations" / "versions"
    parents_of: dict[str, tuple[str, ...]] = {}
    for path in sorted(versions.glob("[0-9]*.py")):
        module = _load_migration(path)
        down = module.down_revision
        if down is None:
            parents = ()
        elif isinstance(down, str):
            parents = (down,)
        else:  # a merge revision names every head it joins
            parents = tuple(str(d) for d in down)
        parents_of[str(module.revision)] = parents

    ordered: list[str] = []
    done: set[str] = set()
    while len(ordered) < len(parents_of):
        ready = sorted(
            rev
            for rev, parents in parents_of.items()
            if rev not in done and all(p in done for p in parents)
        )
        assert ready, "migration chain is broken or forked"
        ordered.extend(ready)
        done.update(ready)

    referenced = {p for parents in parents_of.values() for p in parents}
    heads = sorted(set(parents_of) - referenced)
    assert len(heads) == 1, f"migration chain is broken or forked: heads {heads}"
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
    async with isolated_pool(min_size=2, max_size=8) as pool:
        async with pool.acquire() as conn:
            await conn.execute(ddl())
            await conn.execute(TRUNCATE)
        yield pool


@pytest.fixture
def ledger(ledger_pool: asyncpg.Pool) -> PostgresExecutionLedger:
    return PostgresExecutionLedger(ledger_pool, clock=lambda: CLOCK_NOW)


__all__ = [
    "DSN",
    "TABLES",
    "TRUNCATE",
    "ddl",
    "init_codec",
    "isolated_pool",
    "ledger",
    "ledger_pool",
    "migration_sql",
    "pg_only",
]
