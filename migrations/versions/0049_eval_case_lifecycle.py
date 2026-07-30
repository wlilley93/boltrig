"""Recoverable governed evaluation-case archival.

Revision ID: 0049_eval_case_lifecycle
Revises: 0048_model_endpoint_lifecycle
"""

from __future__ import annotations

from alembic import op

revision = "0049_eval_case_lifecycle"
down_revision = "0048_model_endpoint_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE eval_cases "
        "ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE eval_cases DROP COLUMN IF EXISTS is_active")
