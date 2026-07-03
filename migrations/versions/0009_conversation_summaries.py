"""append-only derived conversation summaries (long-conversation compaction).

An ordered delta bringing an existing database up to carry the derived compaction
summaries the continuity composer reads to keep a long conversation cheap. A fresh
database already gets the table from the baseline replay of store/schema.sql.
Idempotent (CREATE TABLE IF NOT EXISTS), matching schema.sql.

- conversation_summaries: a DERIVED, append-only view of a conversation's OLDER
  turns. Past a threshold the composer sends [summary + recent verbatim tail]
  instead of the whole history. This is derived data, never a mutation of the
  frozen conversation_messages record ([2026] VJS-COUNTY 4): the table is
  INSERT-only, a re-compaction appends a new row covering more messages rather
  than editing an old one. up_to_message_id is the split boundary (the last live
  message the summary covers).

Row-level tenant isolation for this table is applied by the shared rls.sql replay
(which now lists conversation_summaries), matching how the sibling conversation
tables get their policy - not inline in the migration.

Revision ID: 0009_conversation_summaries
Revises: 0008_workflow_promotions
"""

from __future__ import annotations

from alembic import op

revision = "0009_conversation_summaries"
down_revision = "0008_workflow_promotions"
branch_labels = None
depends_on = None

_DDL = """
CREATE TABLE IF NOT EXISTS conversation_summaries (
    id                TEXT NOT NULL,
    conversation_id   TEXT NOT NULL,
    tenant_id         TEXT NOT NULL,
    up_to_message_id  TEXT NOT NULL,
    covered_count     INTEGER NOT NULL,
    summary           TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS conv_summaries_idx
    ON conversation_summaries (tenant_id, conversation_id, covered_count);
"""


def upgrade() -> None:
    op.execute(_DDL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS conversation_summaries;")
