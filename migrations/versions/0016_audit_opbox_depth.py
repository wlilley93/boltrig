"""Opbox-depth audit enrichment + security stream + rollup anchors ([2026] VJS-COUNTY 9).

An ordered delta bringing an existing database up to the Opbox-depth audit. A
fresh database already gets everything from the baseline replay of
store/schema.sql; this migration is the in-place upgrade for a provisioned one.
Idempotent (ADD COLUMN / CREATE TABLE IF NOT EXISTS), matching schema.sql exactly.

ADDITIVE + backward-compatible:
  - D1: the five new audit_log columns (ip_address, user_agent, resource,
    resource_id, workspace_id) are ALL NULLABLE and every existing row is left
    NULL. The audit writer folds a field into the hash ONLY when non-None, so a
    pre-existing row canonicalises byte-for-byte as before and its hash still
    verifies - the tamper-evident chain (SEC-16/K-19) is unchanged.
  - D3: security_log is a NEW, separate hash-chained table for security signals.
  - D4: audit_rollup_anchors is a NEW table for the periodic rollup anchors.

Both new tables carry a real tenant_id, so the RLS overlay (store/rls.sql) fences
them with the generic tenant_id policy - run rls.sql after this on an RLS
deployment (it is idempotent and now lists both tables).

Revision ID: 0016_audit_opbox_depth
Revises: 0015_invitation_workspace_provision
"""

from __future__ import annotations

from alembic import op

revision = "0016_audit_opbox_depth"
down_revision = "0015_invitation_workspace_provision"
branch_labels = None
depends_on = None

_DDL = """
-- D1: enrich audit_log (all nullable, backfilled NULL, chain-safe).
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS ip_address   TEXT;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS user_agent   TEXT;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS resource     TEXT;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS resource_id  TEXT;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS workspace_id TEXT;
CREATE INDEX IF NOT EXISTS audit_ws_idx ON audit_log (tenant_id, workspace_id);
CREATE INDEX IF NOT EXISTS audit_actor_idx ON audit_log (tenant_id, actor);

-- D3: the distinct SecurityEvent stream (its own hash chain).
CREATE TABLE IF NOT EXISTS security_log (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     TEXT NOT NULL,
    seq           BIGINT NOT NULL,
    ts            TIMESTAMPTZ NOT NULL,
    event_type    TEXT NOT NULL,
    reason        TEXT NOT NULL,
    actor         TEXT,
    actor_tier    TEXT,
    workspace_id  TEXT,
    ip_address    TEXT,
    user_agent    TEXT,
    resource      TEXT,
    resource_id   TEXT,
    on_behalf_of  TEXT,
    detail        JSONB,
    prev_hash     TEXT,
    hash          TEXT NOT NULL,
    UNIQUE (tenant_id, seq)
);
CREATE INDEX IF NOT EXISTS security_ts_idx ON security_log (tenant_id, ts);
CREATE INDEX IF NOT EXISTS security_type_idx ON security_log (tenant_id, event_type);

-- D4: periodic per-org/workspace rollup anchors.
CREATE TABLE IF NOT EXISTS audit_rollup_anchors (
    id               TEXT NOT NULL,
    tenant_id        TEXT NOT NULL,
    workspace_id     TEXT,
    seq_start        BIGINT NOT NULL,
    seq_end          BIGINT NOT NULL,
    rollup_root_hash TEXT NOT NULL,
    anchored_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_dev_fallback  BOOLEAN NOT NULL DEFAULT true,
    rfc3161_token    TEXT,
    kms_signature    TEXT,
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS audit_anchor_scope_idx
    ON audit_rollup_anchors (tenant_id, workspace_id, seq_end);
"""

_DOWN = """
DROP TABLE IF EXISTS audit_rollup_anchors;
DROP TABLE IF EXISTS security_log;
ALTER TABLE audit_log DROP COLUMN IF EXISTS workspace_id;
ALTER TABLE audit_log DROP COLUMN IF EXISTS resource_id;
ALTER TABLE audit_log DROP COLUMN IF EXISTS resource;
ALTER TABLE audit_log DROP COLUMN IF EXISTS user_agent;
ALTER TABLE audit_log DROP COLUMN IF EXISTS ip_address;
"""


def upgrade() -> None:
    op.execute(_DDL)


def downgrade() -> None:
    op.execute(_DOWN)
