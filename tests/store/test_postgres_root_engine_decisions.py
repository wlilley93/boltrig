"""PostgresRootEngineDecisionStore: the shared contract holds on real PostgreSQL.

These run only when BOLTRIG_TEST_DATABASE_URL points at a Postgres (CI provides a
service; offline they skip cleanly, P9). They prove the durable adapter satisfies
the same insert-once / replay / conflict / scope semantics as the in-memory
adapter, and that RootRoutingAdmission (slice 2) stays atomic and total over the
durable store.
"""

from __future__ import annotations

import asyncio
import os

import asyncpg
import pytest

from boltrig.fleet.application.codex_routing import RootDecisionConflict
from boltrig.fleet.application.root_admission import RootRoutingAdmission
from boltrig.fleet.domain.codex_rollout import (
    CodexRolloutMode,
    CodexRolloutPolicy,
    RootWorkload,
)
from boltrig.fleet.infrastructure.postgres_root_engine_decisions import (
    PostgresRootEngineDecisionStore,
)
from boltrig.fleet.ports.root_engine_decisions import RootEngineDecisionStore
from tests.contracts.root_admission import facts, scope
from tests.contracts.root_engine_decision_store import (
    assert_concurrent_exact_replay_is_serializable,
    assert_insert_once_replay_conflict_and_scope,
)

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
_pg = pytest.mark.skipif(not DSN, reason="set BOLTRIG_TEST_DATABASE_URL for Postgres tests")

_DDL = """
CREATE TABLE IF NOT EXISTS root_engine_decisions (
    tenant_id               TEXT NOT NULL,
    workspace_id            TEXT NOT NULL,
    root_run_id             TEXT NOT NULL,
    workload                TEXT NOT NULL,
    compatibility           TEXT NOT NULL,
    policy_generation       INT NOT NULL,
    policy_digest           TEXT NOT NULL,
    route                   TEXT NOT NULL,
    execution_result_source TEXT NOT NULL,
    reason_code             TEXT NOT NULL,
    canary_bucket           INT,
    decision_digest         TEXT NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    engine_owner            TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (tenant_id, workspace_id, root_run_id)
)
"""


async def _fresh_store() -> tuple[asyncpg.Pool, RootEngineDecisionStore]:
    pool = await asyncpg.create_pool(dsn=DSN, min_size=1, max_size=8)
    async with pool.acquire() as conn:
        await conn.execute(_DDL)
        await conn.execute("TRUNCATE root_engine_decisions")
    return pool, PostgresRootEngineDecisionStore(pool)


@_pg
async def test_postgres_insert_once_replay_conflict_and_scope() -> None:
    pool, store = await _fresh_store()
    try:
        await assert_insert_once_replay_conflict_and_scope(store)
    finally:
        await pool.close()


@_pg
async def test_postgres_concurrent_exact_replay_is_serializable() -> None:
    pool, store = await _fresh_store()
    try:
        await assert_concurrent_exact_replay_is_serializable(store)
    finally:
        await pool.close()


@_pg
async def test_postgres_store_repr_discloses_no_routing_identifiers() -> None:
    pool, _store = await _fresh_store()
    try:
        assert repr(PostgresRootEngineDecisionStore(pool)) == (
            "PostgresRootEngineDecisionStore(bounded=False)"
        )
    finally:
        await pool.close()


@_pg
async def test_admission_is_atomic_and_total_over_the_durable_store() -> None:
    pool, store = await _fresh_store()
    try:
        admission = RootRoutingAdmission(
            CodexRolloutPolicy(1, mode=CodexRolloutMode.DEFAULT), store
        )
        first_facts = facts("root-1")

        # A new root is routed and persisted; the returned value is the stored one.
        first = await admission.admit(first_facts)
        assert await store.get(first_facts.scope) == first

        # Re-admitting the same trusted facts replays the canonical decision.
        replayed = await admission.admit(first_facts)
        assert replayed == first

        # Concurrent admission of one root resolves to a single persisted value.
        concurrent = await asyncio.gather(
            *(admission.admit(facts("root-race")) for _ in range(32))
        )
        assert {item.digest for item in concurrent} == {concurrent[0].digest}
        assert await store.get(scope("root-race")) == concurrent[0]

        # Facts that drifted from immutable history are rejected without overwrite.
        with pytest.raises(RootDecisionConflict):
            await admission.admit(facts("root-1", workload=RootWorkload.WRITE_CAPABLE))
        assert await store.get(first_facts.scope) == first
    finally:
        await pool.close()
