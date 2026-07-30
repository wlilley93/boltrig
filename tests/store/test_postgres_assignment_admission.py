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
    assert_concurrent_distinct_admissions_are_total,
    assert_concurrent_identical_admissions_are_coherent,
)
from tests.store.execution_ledger_pg import (
    TRUNCATE,
    ddl,
    isolated_pool,
    pg_only,
)
from tests.unit.execution_ledger_fixtures import CLOCK_NOW

_ATTESTATION_TABLES = "capability_attestation_entries, capability_attestation_sets"


def _schema() -> str:
    """The whole shipped chain, including the attestation store's own schema."""

    schema = ddl()
    assert "capability_attestation_sets" in schema
    assert "capability_attestation_entries" in schema
    return schema


@pytest.fixture
async def admission_pool() -> AsyncIterator[asyncpg.Pool]:
    # max_size is well above 1 on purpose: the race proofs must contend on real
    # backends holding real advisory locks in two lock domains, not queue up on
    # the pool and serialize before they ever reach PostgreSQL. Both stores share
    # this pool, exactly as a deployment binds them, so the sequence of
    # acquire/release across the two transactions is the real one.
    async with isolated_pool(min_size=2, max_size=16) as pool:
        async with pool.acquire() as conn:
            await conn.execute(_schema())
            await conn.execute(TRUNCATE)
            await conn.execute(f"TRUNCATE {_ATTESTATION_TABLES}")
        yield pool


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
async def test_postgres_concurrent_admission_of_one_command_is_coherent(
    admission_pool: asyncpg.Pool,
) -> None:
    await assert_concurrent_identical_admissions_are_coherent(*_build(admission_pool))


@pg_only
@pytest.mark.invariant("SEC-163")
async def test_postgres_concurrent_distinct_admissions_in_one_scope_do_not_deadlock(
    admission_pool: asyncpg.Pool,
) -> None:
    await assert_concurrent_distinct_admissions_are_total(*_build(admission_pool))


@pg_only
@pytest.mark.invariant("SEC-163")
async def test_postgres_admission_exposes_no_binding_pin_or_mint_only_bypass(
    admission_pool: asyncpg.Pool,
) -> None:
    admission, _, _ = _build(admission_pool)
    await assert_admission_offers_no_bypass_surface(admission)
