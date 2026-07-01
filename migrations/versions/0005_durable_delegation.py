"""durable delegation: work-item leases, run checkpoints, fan-out counters (Beat 3).

An ordered delta that brings an existing database to the Beat 3 schema; a fresh
database already gets it from the baseline replay of store/schema.sql.
Idempotent (ADD COLUMN / CREATE TABLE / CREATE INDEX IF NOT EXISTS), matching
schema.sql. Leases make a claim single-winner and reclaimable (US-FLT-05);
fanout_counters back the atomic cross-worker fan-out cap (US-EXE-07).

Revision ID: 0005_durable_delegation
Revises: 0004_extension_contract
"""

from __future__ import annotations

from alembic import op

revision = "0005_durable_delegation"
down_revision = "0004_extension_contract"
branch_labels = None
depends_on = None

_DDL = """
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS lease_owner TEXT;
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ;
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS attempts INT NOT NULL DEFAULT 0;
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS degraded BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS result JSONB;
CREATE INDEX IF NOT EXISTS work_items_lease_idx ON work_items (tenant_id, status, lease_expires_at);

CREATE TABLE IF NOT EXISTS run_checkpoints (
    tenant_id       TEXT NOT NULL,
    run_id          TEXT NOT NULL,
    step            TEXT NOT NULL,
    status          TEXT NOT NULL,
    output          JSONB,
    hitl_request_id TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, run_id, step)
);

CREATE TABLE IF NOT EXISTS fanout_counters (
    tenant_id  TEXT NOT NULL,
    tree_id    TEXT NOT NULL,
    counter    TEXT NOT NULL,
    value      INT NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, tree_id, counter)
);
"""


def upgrade() -> None:
    op.execute(_DDL)


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS fanout_counters;
        DROP TABLE IF EXISTS run_checkpoints;
        DROP INDEX IF EXISTS work_items_lease_idx;
        ALTER TABLE work_items DROP COLUMN IF EXISTS result;
        ALTER TABLE work_items DROP COLUMN IF EXISTS degraded;
        ALTER TABLE work_items DROP COLUMN IF EXISTS attempts;
        ALTER TABLE work_items DROP COLUMN IF EXISTS lease_expires_at;
        ALTER TABLE work_items DROP COLUMN IF EXISTS lease_owner;
        """
    )
