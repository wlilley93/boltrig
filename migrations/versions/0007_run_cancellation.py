"""server-side run cancellation ([2026] VJS-COUNTY 6).

An ordered delta bringing an existing database up to carry the cooperative,
owner-only run-cancel signal the WorkPump consults at each step boundary. A
fresh database already gets the table from the baseline replay of
store/schema.sql. Idempotent (CREATE TABLE IF NOT EXISTS), matching schema.sql.

- run_cancel_requests: a marker row keyed (tenant_id, run_id) written THROUGH the
  owner-only audited route; the pump reads is_run_cancel_requested and stops
  BEFORE dispatching the next verb (never mid-adapter). NOT a broad mutable run
  table. The terminal CANCELLED work-item state + a checkpoint are written in a
  finally, so a restart re-detects this row and never resurrects a cancelled run.

Revision ID: 0007_run_cancellation
Revises: 0006_chat_attachments_supersede
"""

from __future__ import annotations

from alembic import op

revision = "0007_run_cancellation"
down_revision = "0006_chat_attachments_supersede"
branch_labels = None
depends_on = None

_DDL = """
CREATE TABLE IF NOT EXISTS run_cancel_requests (
    tenant_id     TEXT NOT NULL,
    run_id        TEXT NOT NULL,
    requested_by  TEXT NOT NULL,
    requested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, run_id)
);
"""

# Row-level tenant isolation for this table is applied by the shared rls.sql
# replay (which now lists run_cancel_requests), matching how the Beat 3 tables
# (run_checkpoints, fanout_counters) get their policy - not inline in the migration.


def upgrade() -> None:
    op.execute(_DDL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS run_cancel_requests;")
