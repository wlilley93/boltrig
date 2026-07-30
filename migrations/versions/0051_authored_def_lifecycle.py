"""Recoverable authored skill, noun, and verb lifecycle.

Revision ID: 0051_authored_def_lifecycle
Revises: 0050_workflow_triggers
"""

from __future__ import annotations

from alembic import op

revision = "0051_authored_def_lifecycle"
down_revision = "0050_workflow_triggers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE skills
          ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
        ALTER TABLE nouns
          ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
        ALTER TABLE verbs
          ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE verbs DROP COLUMN IF EXISTS is_active;
        ALTER TABLE nouns DROP COLUMN IF EXISTS is_active;
        ALTER TABLE skills DROP COLUMN IF EXISTS is_active;
        """
    )
