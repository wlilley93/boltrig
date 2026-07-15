"""Bind HITL visibility and queued work to originating workspace scope.

Revision ID: 0025_hitl_access_scope
Revises: 0024_bound_idempotency
"""

from __future__ import annotations

from alembic import op

revision = "0025_hitl_access_scope"
down_revision = "0024_bound_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE work_items ADD COLUMN IF NOT EXISTS workspace_id TEXT"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS work_items_workspace_idx "
        "ON work_items (tenant_id, workspace_id)"
    )
    op.execute(
        "ALTER TABLE hitl_requests ADD COLUMN IF NOT EXISTS workspace_id TEXT"
    )
    op.execute(
        "ALTER TABLE hitl_requests ADD COLUMN IF NOT EXISTS department_scope JSONB"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE hitl_requests DROP COLUMN IF EXISTS department_scope")
    op.execute("ALTER TABLE hitl_requests DROP COLUMN IF EXISTS workspace_id")
    op.execute("DROP INDEX IF EXISTS work_items_workspace_idx")
    op.execute("ALTER TABLE work_items DROP COLUMN IF EXISTS workspace_id")
