"""eval-gated workflow reuse ranking ([2026] VJS-COUNTY 5).

An ordered delta bringing an existing database up to carry the reuse-ranking
record the workflow matcher reads. A fresh database already gets the table from
the baseline replay of store/schema.sql. Idempotent (CREATE TABLE IF NOT EXISTS),
matching schema.sql.

- workflow_promotions: a ranking-only row keyed (tenant_id, workflow_id). A
  generated/learned workflow becomes a promotion CANDIDATE, is PROMOTED once it
  passes its eval cases (run through the kernel chokepoint under the initiator
  ceiling, reusing the SEC-29 no-escalation guarantee), and DEMOTED if a later
  eval fails. It carries NO authority column - execution authority still comes
  only from the caller ceiling at dispatch; this only tunes reuse likelihood
  (competence, never authority).

Revision ID: 0008_workflow_promotions
Revises: 0007_run_cancellation
"""

from __future__ import annotations

from alembic import op

revision = "0008_workflow_promotions"
down_revision = "0007_run_cancellation"
branch_labels = None
depends_on = None

_DDL = """
CREATE TABLE IF NOT EXISTS workflow_promotions (
    workflow_id TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    state       TEXT NOT NULL DEFAULT 'candidate',
    score       DOUBLE PRECISION NOT NULL DEFAULT 0,
    eval_run_id TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workflow_id)
);
"""

# Row-level tenant isolation for this table is applied by the shared rls.sql
# replay (which now lists workflow_promotions), matching how the sibling library
# tables get their policy - not inline in the migration.


def upgrade() -> None:
    op.execute(_DDL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS workflow_promotions;")
