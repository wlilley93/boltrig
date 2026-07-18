"""PostgresModelProxyGrantStore: the shared contract holds on real PostgreSQL.

Runs only when BOLTRIG_TEST_DATABASE_URL points at a Postgres (CI provides a
service; offline the class skips cleanly, P9). Proves the durable adapter
satisfies the same atomic insert / lookup / collision / generation-CAS /
hierarchical-cancellation / expiry semantics as the in-memory adapter via the
shared ModelProxyGrantStoreContract.

Note: the async ``_pool`` fixture below is deliberately function-scoped (no
``scope=`` argument). This repo's pytest-asyncio runs in "auto" mode with no
``asyncio_default_fixture_loop_scope`` override, so each async test function
gets its own event loop; a module-scoped asyncpg.Pool fixture shared across
tests would attach to one test's loop and then break on the next with
"attached to a different loop".
"""

from __future__ import annotations

import os

import asyncpg
import pytest

from boltrig.fleet.infrastructure.postgres_model_proxy_grants import PostgresModelProxyGrantStore
from boltrig.fleet.ports.model_proxy_grants import ModelProxyGrantStore
from tests.contracts.model_proxy_grant_store import ModelProxyGrantStoreContract

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
_pg = pytest.mark.skipif(not DSN, reason="set BOLTRIG_TEST_DATABASE_URL for Postgres tests")

_DDL = """
CREATE TABLE IF NOT EXISTS model_proxy_grants (
    grant_id                     TEXT NOT NULL,
    tenant_id                    TEXT NOT NULL,
    workspace_id                 TEXT NOT NULL,
    root_run_id                  TEXT NOT NULL,
    phase_id                     TEXT NOT NULL,
    assignment_id                TEXT NOT NULL,
    cell_id                      TEXT NOT NULL,
    pid                          BIGINT NOT NULL,
    pid_start_ticks              BIGINT NOT NULL,
    boot_id                      TEXT NOT NULL,
    pid_namespace_inode          BIGINT NOT NULL,
    cgroup_identity_digest       TEXT NOT NULL,
    model_id                     TEXT NOT NULL,
    model_policy_digest          TEXT NOT NULL,
    budget_id                    TEXT NOT NULL,
    max_input_tokens             BIGINT NOT NULL,
    max_output_tokens            BIGINT NOT NULL,
    max_total_tokens             BIGINT NOT NULL,
    max_cost_micros              BIGINT NOT NULL,
    budget_policy_digest         TEXT NOT NULL,
    bearer_digest                TEXT NOT NULL,
    startup_request_digest       TEXT NOT NULL,
    issued_at                    TIMESTAMPTZ NOT NULL,
    expires_at                   TIMESTAMPTZ NOT NULL,
    generation                   BIGINT NOT NULL,
    status                       TEXT NOT NULL,
    revoked_at                   TIMESTAMPTZ,
    revocation_reason            TEXT,
    created_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
    engine_owner                 TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (grant_id)
);
CREATE TABLE IF NOT EXISTS model_proxy_grant_cancelled_roots (
    tenant_id       TEXT NOT NULL,
    workspace_id    TEXT NOT NULL,
    root_run_id     TEXT NOT NULL,
    cancelled_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    reason          TEXT NOT NULL,
    engine_owner    TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (tenant_id, workspace_id, root_run_id)
);
CREATE TABLE IF NOT EXISTS model_proxy_grant_cancelled_phases (
    tenant_id       TEXT NOT NULL,
    workspace_id    TEXT NOT NULL,
    root_run_id     TEXT NOT NULL,
    phase_id        TEXT NOT NULL,
    cancelled_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    reason          TEXT NOT NULL,
    engine_owner    TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (tenant_id, workspace_id, root_run_id, phase_id)
);
CREATE TABLE IF NOT EXISTS model_proxy_grant_cancelled_assignments (
    tenant_id       TEXT NOT NULL,
    workspace_id    TEXT NOT NULL,
    root_run_id     TEXT NOT NULL,
    phase_id        TEXT NOT NULL,
    assignment_id   TEXT NOT NULL,
    cancelled_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    reason          TEXT NOT NULL,
    engine_owner    TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (tenant_id, workspace_id, root_run_id, phase_id, assignment_id)
);
CREATE TABLE IF NOT EXISTS model_proxy_grant_cancelled_cells (
    tenant_id                TEXT NOT NULL,
    workspace_id             TEXT NOT NULL,
    root_run_id              TEXT NOT NULL,
    phase_id                 TEXT NOT NULL,
    assignment_id            TEXT NOT NULL,
    cell_id                  TEXT NOT NULL,
    pid                      BIGINT NOT NULL,
    pid_start_ticks          BIGINT NOT NULL,
    boot_id                  TEXT NOT NULL,
    pid_namespace_inode      BIGINT NOT NULL,
    cgroup_identity_digest   TEXT NOT NULL,
    cancelled_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    reason                   TEXT NOT NULL,
    engine_owner             TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (
        tenant_id, workspace_id, root_run_id, phase_id, assignment_id,
        cell_id, pid, pid_start_ticks, boot_id, pid_namespace_inode,
        cgroup_identity_digest
    )
)
"""

_TRUNCATE = (
    "TRUNCATE model_proxy_grants, model_proxy_grant_cancelled_roots, "
    "model_proxy_grant_cancelled_phases, model_proxy_grant_cancelled_assignments, "
    "model_proxy_grant_cancelled_cells"
)


@pytest.fixture
async def _pool() -> asyncpg.Pool:
    pool = await asyncpg.create_pool(dsn=DSN, min_size=1, max_size=8)
    async with pool.acquire() as conn:
        await conn.execute(_DDL)
    yield pool
    await pool.close()


@_pg
class TestPostgresModelProxyGrantStore(ModelProxyGrantStoreContract):
    @pytest.fixture
    async def grant_store(self, _pool: asyncpg.Pool) -> ModelProxyGrantStore:
        async with _pool.acquire() as conn:
            await conn.execute(_TRUNCATE)
        return PostgresModelProxyGrantStore(_pool)
