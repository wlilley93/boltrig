"""Bind approvals to the exact request and delegated initiator.

Revision ID: 0023_hitl_request_binding
Revises: 0022_schema_parity
"""

from __future__ import annotations

from alembic import op

revision = "0023_hitl_request_binding"
down_revision = "0022_schema_parity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE hitl_requests "
        "ADD COLUMN IF NOT EXISTS requested_on_behalf_of TEXT"
    )
    op.execute(
        "ALTER TABLE hitl_requests "
        "ADD COLUMN IF NOT EXISTS request_fingerprint TEXT"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE hitl_requests DROP COLUMN IF EXISTS request_fingerprint")
    op.execute("ALTER TABLE hitl_requests DROP COLUMN IF EXISTS requested_on_behalf_of")
