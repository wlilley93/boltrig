"""PostgresCapabilityAttestationStore: the shared contract holds on real PostgreSQL.

Runs only when BOLTRIG_TEST_DATABASE_URL points at a Postgres (CI provides a
service; offline the module skips cleanly, P9). Proves the durable adapter
satisfies the same insert-once / exact-replay / conflict / fail-closed-resolve
semantics as the in-memory adapter, including the concurrent CAS race, via the
shared CapabilityAttestationStoreContract helpers.
"""

from __future__ import annotations

import os

import asyncpg
import pytest

from boltrig.fleet.infrastructure.postgres_capability_attestations import (
    PostgresCapabilityAttestationStore,
)
from tests.contracts.capability_attestation_store import (
    assert_concurrent_exact_replay_is_serializable,
    assert_insert_once_replay_conflict_and_resolve,
)

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
_pg = pytest.mark.skipif(not DSN, reason="set BOLTRIG_TEST_DATABASE_URL for Postgres tests")

_DDL = """
CREATE TABLE IF NOT EXISTS capability_attestation_sets (
    tenant_id                     TEXT NOT NULL,
    workspace_id                  TEXT NOT NULL,
    root_run_id                   TEXT NOT NULL,
    phase_id                      TEXT NOT NULL,
    assignment_id                 TEXT NOT NULL,
    authority_evaluation_id       TEXT NOT NULL,
    authority_evaluation_digest   TEXT NOT NULL,
    authority_policy_generation   BIGINT NOT NULL,
    catalog_generation            BIGINT NOT NULL,
    catalog_digest                TEXT NOT NULL,
    set_digest                    TEXT NOT NULL,
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    engine_owner                  TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (tenant_id, workspace_id, root_run_id, phase_id, assignment_id)
);
CREATE TABLE IF NOT EXISTS capability_attestation_entries (
    tenant_id           TEXT NOT NULL,
    workspace_id        TEXT NOT NULL,
    root_run_id         TEXT NOT NULL,
    phase_id            TEXT NOT NULL,
    assignment_id       TEXT NOT NULL,
    verb_id             TEXT NOT NULL,
    definition_digest   TEXT NOT NULL,
    effect_class        TEXT NOT NULL,
    consequence         TEXT NOT NULL,
    engine_owner        TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (
        tenant_id, workspace_id, root_run_id, phase_id, assignment_id, verb_id
    ),
    FOREIGN KEY (
        tenant_id, workspace_id, root_run_id, phase_id, assignment_id
    ) REFERENCES capability_attestation_sets (
        tenant_id, workspace_id, root_run_id, phase_id, assignment_id
    ) ON DELETE CASCADE
)
"""

_TRUNCATE = "TRUNCATE capability_attestation_entries, capability_attestation_sets"


@pytest.fixture
async def _pool() -> asyncpg.Pool:
    pool = await asyncpg.create_pool(dsn=DSN, min_size=1, max_size=8)
    async with pool.acquire() as conn:
        await conn.execute(_DDL)
        await conn.execute(_TRUNCATE)
    yield pool
    await pool.close()


@_pg
async def test_postgres_insert_once_replay_conflict_and_resolve(_pool: asyncpg.Pool) -> None:
    await assert_insert_once_replay_conflict_and_resolve(PostgresCapabilityAttestationStore(_pool))


@_pg
async def test_postgres_concurrent_exact_replay_is_serializable(_pool: asyncpg.Pool) -> None:
    await assert_concurrent_exact_replay_is_serializable(PostgresCapabilityAttestationStore(_pool))


@_pg
async def test_postgres_store_repr_discloses_no_evidence(_pool: asyncpg.Pool) -> None:
    assert repr(PostgresCapabilityAttestationStore(_pool)) == (
        "PostgresCapabilityAttestationStore(bounded=False)"
    )
