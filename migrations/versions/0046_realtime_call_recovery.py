"""Durable governed voice profile selection.

Revision ID: 0046_realtime_call_recovery
Revises: 0045_password_reset
"""

from alembic import op

revision = "0046_realtime_call_recovery"
down_revision = "0045_password_reset"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE realtime_calls "
        "ADD COLUMN IF NOT EXISTS agent_profile_id TEXT, "
        "ADD COLUMN IF NOT EXISTS model_profile_id TEXT"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE realtime_calls "
        "DROP COLUMN IF EXISTS model_profile_id, "
        "DROP COLUMN IF EXISTS agent_profile_id"
    )
