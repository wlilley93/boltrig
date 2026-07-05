"""workflow run records (design brief 22.1).

An ordered delta bringing an existing database up to carry one row per workflow
execution, recorded after a successful execute. The automations home cards read
the aggregated stats (run_count, success_count, last_run_at) from this table to
show REAL numbers instead of deterministic placeholders. A fresh database already
gets the table from the baseline replay of store/schema.sql; this migration is
the in-place upgrade for a provisioned one. Idempotent (CREATE TABLE IF NOT
EXISTS), matching schema.sql.

Observability-only: a write failure is swallowed by the route so it can NEVER
break workflow execution. Tenant-scoped (SEC-08); RLS-listed in rls.sql.

Revision ID: 0020_workflow_run_records
Revises: 0019_cross_tenant_identity
"""

from __future__ import annotations

from alembic import op

revision = "0020_workflow_run_records"
down_revision = "0019_cross_tenant_identity"
branch_labels = None
depends_on = None

_DDL = """
CREATE TABLE IF NOT EXISTS workflow_run_records (
    tenant_id   TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    run_id      TEXT NOT NULL,
    status      TEXT NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, run_id)
);
CREATE INDEX IF NOT EXISTS workflow_run_records_wf_idx
    ON workflow_run_records (tenant_id, workflow_id);
"""

_DOWN = """
DROP INDEX IF EXISTS workflow_run_records_wf_idx;
DROP TABLE IF EXISTS workflow_run_records;
"""


# Row-level tenant isolation for this table is applied by the shared rls.sql
# replay (which now lists workflow_run_records), matching how the sibling
# library tables get their policy - not inline in the migration.


def upgrade() -> None:
    op.execute(_DDL)


def downgrade() -> None:
    op.execute(_DOWN)
