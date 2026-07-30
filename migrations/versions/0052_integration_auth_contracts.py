"""Closed integration auth contracts and one active adapter credential.

Revision ID: 0052_integration_auth_contracts
Revises: 0051_authored_def_lifecycle
"""

from __future__ import annotations

from alembic import op

revision = "0052_integration_auth_contracts"
down_revision = "0051_authored_def_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE integration_catalogue
          ADD COLUMN IF NOT EXISTS secret_contract JSONB;
        CREATE UNIQUE INDEX IF NOT EXISTS
          integration_connections_one_active_adapter_idx
          ON integration_connections(tenant_id, adapter_id)
          WHERE health <> 'revoked';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS integration_connections_one_active_adapter_idx;
        ALTER TABLE integration_catalogue
          DROP COLUMN IF EXISTS secret_contract;
        """
    )
