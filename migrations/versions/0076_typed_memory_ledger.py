"""Typed memory planes: slot keys, versions, write-gate status, events.

Decision 0029. Semantic and procedural memory get stable logical slots
(``memory_key``), monotonic versions and a write-gate state machine; exactly
one ``active`` row per (tenant, slot) may exist, enforced by partial unique
indexes (a DB-level arbitrator for concurrent writes). Episodes are append-only
and carry no key. ``memory_events`` is the append-only audit trail of gate
decisions. Existing rows are untouched: they keep status='active' (the
default) and a NULL memory_key, which the partial unique indexes treat as
distinct, so legacy facts never collide with typed slots.

Revision ID: 0076_typed_memory_ledger
Revises: 0075_routine_conversations
"""

from __future__ import annotations

from alembic import op

revision = "0076_typed_memory_ledger"
down_revision = "0075_routine_conversations"
branch_labels = None
depends_on = None

_UP = """
ALTER TABLE memory_facts
    ADD COLUMN IF NOT EXISTS memory_key TEXT,
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active',
    ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS confidence REAL,
    ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS valid_to TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS supersedes_id TEXT;

ALTER TABLE memory_facts
    DROP CONSTRAINT IF EXISTS memory_facts_status_check,
    ADD CONSTRAINT memory_facts_status_check
        CHECK (status IN ('candidate', 'active', 'superseded', 'rejected'));

-- One current value per slot (MEM-TYP-01): the DB arbitrates concurrent
-- same-slot writes; legacy rows have NULL memory_key and never collide.
CREATE UNIQUE INDEX IF NOT EXISTS one_active_semantic_fact_per_slot
    ON memory_facts (tenant_id, memory_key)
    WHERE kind = 'semantic' AND status = 'active';
CREATE UNIQUE INDEX IF NOT EXISTS one_active_procedure_per_slot
    ON memory_facts (tenant_id, memory_key)
    WHERE kind = 'procedural' AND status = 'active';

CREATE INDEX IF NOT EXISTS memory_facts_slot_idx
    ON memory_facts (tenant_id, memory_key, kind, status);
CREATE INDEX IF NOT EXISTS memory_facts_candidate_idx
    ON memory_facts (tenant_id, status) WHERE status = 'candidate';

CREATE TABLE IF NOT EXISTS memory_events (
    id             TEXT NOT NULL,
    tenant_id      TEXT NOT NULL,
    memory_id      TEXT,
    memory_key     TEXT,
    event          TEXT NOT NULL CHECK (event IN (
                       'candidate_created', 'candidate_rejected', 'memory_approved',
                       'memory_activated', 'memory_superseded', 'memory_confirmed')),
    decision       TEXT,
    policy_version TEXT NOT NULL DEFAULT 'typed-write-v1',
    detail         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS memory_events_memory_idx
    ON memory_events (tenant_id, memory_id, created_at);
CREATE INDEX IF NOT EXISTS memory_events_key_idx
    ON memory_events (tenant_id, memory_key, created_at);
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS memory_events;
        DROP INDEX IF EXISTS memory_facts_candidate_idx;
        DROP INDEX IF EXISTS memory_facts_slot_idx;
        DROP INDEX IF EXISTS one_active_procedure_per_slot;
        DROP INDEX IF EXISTS one_active_semantic_fact_per_slot;
        ALTER TABLE memory_facts
            DROP CONSTRAINT IF EXISTS memory_facts_status_check;
        ALTER TABLE memory_facts
            DROP COLUMN IF EXISTS supersedes_id,
            DROP COLUMN IF EXISTS payload,
            DROP COLUMN IF EXISTS valid_to,
            DROP COLUMN IF EXISTS valid_from,
            DROP COLUMN IF EXISTS confidence,
            DROP COLUMN IF EXISTS version,
            DROP COLUMN IF EXISTS status,
            DROP COLUMN IF EXISTS memory_key;
        """
    )
