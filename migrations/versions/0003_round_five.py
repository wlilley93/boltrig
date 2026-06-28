"""round five: structured memory governance (facts, ingestions, erasures).

An ordered delta that brings an existing database to the Round Five schema; a
fresh database already gets these tables from the baseline replay of
store/schema.sql. Idempotent (CREATE TABLE IF NOT EXISTS), matching schema.sql.

Revision ID: 0003_round_five
Revises: 0002_round_four
"""

from __future__ import annotations

from alembic import op

revision = "0003_round_five"
down_revision = "0002_round_four"
branch_labels = None
depends_on = None

_DDL = """
CREATE TABLE IF NOT EXISTS memory_facts (
    id            TEXT NOT NULL,
    tenant_id     TEXT NOT NULL,
    owner_scope   TEXT NOT NULL,
    engine_ref    TEXT NOT NULL,
    kind          TEXT NOT NULL,
    source_kind   TEXT NOT NULL,
    source_ref    TEXT,
    data_class    TEXT NOT NULL DEFAULT 'standard',
    content       TEXT NOT NULL DEFAULT '',
    redacted      BOOLEAN NOT NULL DEFAULT false,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS memory_facts_scope_idx ON memory_facts (tenant_id, owner_scope, kind);
CREATE INDEX IF NOT EXISTS memory_facts_source_idx ON memory_facts (tenant_id, source_kind, source_ref);

CREATE TABLE IF NOT EXISTS memory_ingestions (
    id             TEXT NOT NULL,
    tenant_id      TEXT NOT NULL,
    source_kind    TEXT NOT NULL,
    source_ref     TEXT NOT NULL,
    owner_scope    TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending',
    hatchet_run_id TEXT,
    facts_added    INT NOT NULL DEFAULT 0,
    screened       BOOLEAN NOT NULL DEFAULT false,
    detail         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS memory_erasures (
    id                 TEXT NOT NULL,
    tenant_id          TEXT NOT NULL,
    requested_by       TEXT NOT NULL,
    target             TEXT NOT NULL,
    scope              TEXT NOT NULL,
    engine_confirmed   BOOLEAN NOT NULL DEFAULT false,
    transcript_handled BOOLEAN NOT NULL DEFAULT false,
    facts_removed      INT NOT NULL DEFAULT 0,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at       TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, id)
);
"""


def upgrade() -> None:
    op.execute(_DDL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS memory_erasures, memory_ingestions, memory_facts CASCADE")
