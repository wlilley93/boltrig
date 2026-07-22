"""Channel gateway Phase-2 addressing: the work item carries the route target
(tier-1 CoS by default, a named tier-2 subagent/run when addressed) and the
reply route for round-trip delivery back to the originating surface/thread
(decision 0003).

Revision ID: 0036_channel_addressing
Revises: 0035_channel_durability
"""

from __future__ import annotations

from alembic import op

revision = "0036_channel_addressing"
down_revision = "0035_channel_durability"
branch_labels = None
depends_on = None

# Row-level tenant isolation is unchanged: both columns ride the existing
# work_items RLS policy (the table is already tenant-scoped).
DDL = r"""
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS target TEXT;
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS reply_route JSONB;
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE work_items DROP COLUMN IF EXISTS reply_route;
        ALTER TABLE work_items DROP COLUMN IF EXISTS target;
        """
    )
