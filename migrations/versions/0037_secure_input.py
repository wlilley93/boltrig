"""SEC-181 secure input: hitl_requests carries the secure-question marker.

A secure question's answer is sealed via the credential seam and never recorded,
so the marker must persist with the request - without these columns a Postgres
deployment would silently downgrade a secure question to plaintext recording.

Revision ID: 0037_secure_input
Revises: 0036_channel_addressing
"""

from __future__ import annotations

from alembic import op

revision = "0037_secure_input"
down_revision = "0036_channel_addressing"
branch_labels = None
depends_on = None

# Row-level tenant isolation is unchanged: both columns ride the existing
# hitl_requests RLS policy (the table is already tenant-scoped).
DDL = r"""
ALTER TABLE hitl_requests ADD COLUMN IF NOT EXISTS secure BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE hitl_requests ADD COLUMN IF NOT EXISTS secure_purpose TEXT;
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE hitl_requests DROP COLUMN IF EXISTS secure_purpose;
        ALTER TABLE hitl_requests DROP COLUMN IF EXISTS secure;
        """
    )
