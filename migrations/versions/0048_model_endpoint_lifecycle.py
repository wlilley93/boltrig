"""Recoverable governed model-endpoint withdrawal.

Revision ID: 0048_model_endpoint_lifecycle
Revises: 0047_audit_read_indexes
"""

from __future__ import annotations

from alembic import op

revision = "0048_model_endpoint_lifecycle"
down_revision = "0047_audit_read_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE model_endpoints "
        "ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE model_endpoints DROP COLUMN IF EXISTS is_active"
    )
