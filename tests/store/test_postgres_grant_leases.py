"""PostgresGrantLeaseStore: the shared contract holds on real PostgreSQL.

Runs only when BOLTRIG_TEST_DATABASE_URL points at a Postgres (CI provides a
service; offline the class skips cleanly, P9). Proves the durable adapter
satisfies the same atomic issue / replay / collision / authority / tombstone
semantics as the in-memory adapter, including the CAS races, via the shared
GrantLeaseStoreContract.
"""

from __future__ import annotations

import json
import os

import asyncpg
import pytest

from boltrig.fleet.domain.grant_lease import GrantAuthoritySnapshot
from boltrig.fleet.infrastructure.postgres_grant_leases import PostgresGrantLeaseStore
from boltrig.fleet.ports.grant_leases import GrantLeaseStore
from tests.contracts.grant_lease_store import GrantLeaseStoreContract

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
_pg = pytest.mark.skipif(not DSN, reason="set BOLTRIG_TEST_DATABASE_URL for Postgres tests")

_DDL = """
CREATE TABLE IF NOT EXISTS grant_leases (
    lease_id                          TEXT NOT NULL,
    tenant_id                         TEXT NOT NULL,
    workspace_id                      TEXT NOT NULL,
    root_run_id                       TEXT NOT NULL,
    phase_id                          TEXT NOT NULL,
    assignment_id                     TEXT NOT NULL,
    issue_operation_id                TEXT NOT NULL,
    token_digest                      TEXT NOT NULL,
    authority_evaluation_id           TEXT NOT NULL,
    authority_evaluation_digest       TEXT NOT NULL,
    authority_policy_generation       BIGINT NOT NULL,
    permitted_verbs                   JSONB NOT NULL,
    issued_at                         TIMESTAMPTZ NOT NULL,
    expires_at                        TIMESTAMPTZ NOT NULL,
    max_ttl_seconds                   INT NOT NULL,
    expected_current_lease_generation BIGINT,
    lease_generation                  BIGINT NOT NULL,
    status                            TEXT NOT NULL,
    revoked_at                        TIMESTAMPTZ,
    revocation_reason                 TEXT,
    created_at                        TIMESTAMPTZ NOT NULL DEFAULT now(),
    engine_owner                      TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (lease_id)
);
CREATE TABLE IF NOT EXISTS grant_authority_snapshots (
    tenant_id                     TEXT NOT NULL,
    workspace_id                  TEXT NOT NULL,
    root_run_id                   TEXT NOT NULL,
    phase_id                      TEXT NOT NULL,
    assignment_id                 TEXT NOT NULL,
    authority_evaluation_id       TEXT NOT NULL,
    authority_evaluation_digest   TEXT NOT NULL,
    authority_policy_generation   BIGINT NOT NULL,
    permitted_verbs               JSONB NOT NULL,
    installed_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    engine_owner                  TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (tenant_id, workspace_id, root_run_id, phase_id, assignment_id)
);
CREATE TABLE IF NOT EXISTS grant_lease_cancelled_assignments (
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
CREATE TABLE IF NOT EXISTS grant_lease_cancelled_roots (
    tenant_id       TEXT NOT NULL,
    workspace_id    TEXT NOT NULL,
    root_run_id     TEXT NOT NULL,
    cancelled_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    reason          TEXT NOT NULL,
    engine_owner    TEXT NOT NULL DEFAULT 'boltrig',
    PRIMARY KEY (tenant_id, workspace_id, root_run_id)
)
"""

_TRUNCATE = (
    "TRUNCATE grant_leases, grant_authority_snapshots, "
    "grant_lease_cancelled_assignments, grant_lease_cancelled_roots"
)


async def _init_codec(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


@pytest.fixture
async def _pool() -> asyncpg.Pool:
    pool = await asyncpg.create_pool(dsn=DSN, min_size=1, max_size=8, init=_init_codec)
    async with pool.acquire() as conn:
        await conn.execute(_DDL)
    yield pool
    await pool.close()


@_pg
class TestPostgresGrantLeaseStore(GrantLeaseStoreContract):
    @pytest.fixture
    async def grant_store(self, _pool: asyncpg.Pool) -> GrantLeaseStore:
        async with _pool.acquire() as conn:
            await conn.execute(_TRUNCATE)
        return PostgresGrantLeaseStore(_pool)

    @pytest.fixture
    def grant_authority_installer(self, grant_store: GrantLeaseStore):
        async def install(snapshot: GrantAuthoritySnapshot, now) -> None:
            await grant_store.install_authority_snapshot(snapshot, now=now)  # type: ignore[attr-defined]

        return install
