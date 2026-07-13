"""work item run lookup index.

Adds the index used by the run-events authorization path to resolve a run's
owning work item directly instead of scanning every visible work item for a
department-scoped caller.

Revision ID: 0021_work_items_run_lookup
Revises: 0020_workflow_run_records
"""

from __future__ import annotations

from alembic import op

revision = "0021_work_items_run_lookup"
down_revision = "0020_workflow_run_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS work_items_hatchet_run_idx "
        "ON work_items (tenant_id, hatchet_run_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS work_items_hatchet_run_idx")
