"""Fence external-MCP evidence to the exact registration revision.

Revision ID: 0064_mcp_registration_revision
Revises: 0063_mcp_lifecycle_receipts
"""

from __future__ import annotations

from alembic import op

revision = "0064_mcp_registration_revision"
down_revision = "0063_mcp_lifecycle_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE mcp_servers
          ADD COLUMN IF NOT EXISTS config_revision BIGINT NOT NULL DEFAULT 1;
        ALTER TABLE mcp_servers
          DROP CONSTRAINT IF EXISTS mcp_servers_config_revision_check,
          ADD CONSTRAINT mcp_servers_config_revision_check
            CHECK (config_revision >= 1);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE mcp_servers
          DROP CONSTRAINT IF EXISTS mcp_servers_config_revision_check,
          DROP COLUMN IF EXISTS config_revision;
        """
    )
