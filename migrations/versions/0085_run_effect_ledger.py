"""The durable run-effect ledger: what each run changed, and how to undo it.

One row per consequential verb a run completed, appended by the dispatch
chokepoint. ``inverse_verb`` NULL means no inverse exists and the row is
``not_undoable`` - the ledger records that honestly rather than omitting the
effect. Revert walks a run's rows seq-DESCENDING (LIFO) and executes each
inverse back through dispatch, so undo is governed, audited and HITL-gated
exactly like the call it compensates.

Revision ID: 0085_run_effect_ledger
Revises: 0084_named_agent_mailboxes
"""

from __future__ import annotations

from alembic import op

revision = "0085_run_effect_ledger"
down_revision = "0084_named_agent_mailboxes"
branch_labels = None
depends_on = None

TABLES = """
CREATE TABLE IF NOT EXISTS run_effects (
    tenant_id       TEXT NOT NULL,
    run_id          TEXT NOT NULL,
    seq             INTEGER NOT NULL,
    verb_id         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'recorded',
    inverse_verb    TEXT,
    inverse_params  JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary         TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, run_id, seq),
    CHECK (status IN ('recorded','not_undoable','reverted','revert_failed')),
    CHECK ((inverse_verb IS NULL) = (status = 'not_undoable')
           OR status IN ('reverted','revert_failed')),
    CHECK (octet_length(summary) <= 512),
    CHECK (pg_column_size(inverse_params) <= 16384)
);
CREATE INDEX IF NOT EXISTS run_effects_revert_idx
  ON run_effects(tenant_id, run_id, status, seq DESC);
"""


def upgrade() -> None:
    op.execute(TABLES)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS run_effects;")
