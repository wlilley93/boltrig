"""AssignmentAdmission over the durable stores: the shared contract holds on PostgreSQL.

Runs only when BOLTRIG_TEST_DATABASE_URL points at a Postgres (CI provides a
service; offline the module skips cleanly, P9). The service depends on the
ExecutionLedgerStore and CapabilityAttestationStore Protocols only, so the very
assertions the in-memory adapters satisfy are replayed here against the durable
ones, over two genuinely separate stores sharing no transaction.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import asyncpg
import pytest

from boltrig.fleet.application.assignment_admission import AssignmentAdmission
from boltrig.fleet.infrastructure.postgres_capability_attestations import (
    PostgresCapabilityAttestationStore,
)
from boltrig.fleet.infrastructure.postgres_execution_ledger import PostgresExecutionLedger
from tests.contracts.assignment_admission import (
    assert_admission_is_idempotent_on_replay,
    assert_admission_mints_attests_and_persists,
    assert_admission_offers_no_bypass_surface,
)
from tests.store.execution_ledger_pg import (
    DSN,
    TRUNCATE,
    ddl,
    init_codec,
    migration_sql,
    pg_only,
)
from tests.unit.execution_ledger_fixtures import CLOCK_NOW

_ATTESTATION_TABLES = "capability_attestation_entries, capability_attestation_sets"


def _schema() -> str:
    """Both shipped schemas: the ledger's and the attestation store's own."""

    return ";\n".join((ddl(), *migration_sql("0030_capability_attestations")))


@pytest.fixture
async def admission_pool() -> AsyncIterator[asyncpg.Pool]:
    pool = await asyncpg.create_pool(dsn=DSN, min_size=2, max_size=8, init=init_codec)
    assert pool is not None
    async with pool.acquire() as conn:
        await conn.execute(_schema())
        await conn.execute(TRUNCATE)
        await conn.execute(f"TRUNCATE {_ATTESTATION_TABLES}")
    yield pool
    await pool.close()


def _build(
    pool: asyncpg.Pool,
) -> tuple[AssignmentAdmission, PostgresCapabilityAttestationStore, PostgresExecutionLedger]:
    attestations = PostgresCapabilityAttestationStore(pool)
    ledger = PostgresExecutionLedger(pool, clock=lambda: CLOCK_NOW)
    return AssignmentAdmission(attestations, ledger), attestations, ledger


@pg_only
@pytest.mark.invariant("SEC-163")
async def test_postgres_admission_mints_attests_and_persists(
    admission_pool: asyncpg.Pool,
) -> None:
    await assert_admission_mints_attests_and_persists(*_build(admission_pool))


@pg_only
@pytest.mark.invariant("SEC-163")
async def test_postgres_admitting_the_same_trusted_facts_twice_replays(
    admission_pool: asyncpg.Pool,
) -> None:
    await assert_admission_is_idempotent_on_replay(*_build(admission_pool))


@pg_only
@pytest.mark.invariant("SEC-163")
async def test_postgres_admission_exposes_no_binding_pin_or_mint_only_bypass(
    admission_pool: asyncpg.Pool,
) -> None:
    admission, _, _ = _build(admission_pool)
    await assert_admission_offers_no_bypass_surface(admission)
