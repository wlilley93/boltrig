"""Add durable single-owner leases for socket-channel gateways.

Revision ID: 0062_channel_gateway_owner_leases
Revises: 0061_budget_windows
"""

from __future__ import annotations

from alembic import op

revision = "0062_channel_gateway_owner_leases"
down_revision = "0061_budget_windows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS channel_gateway_leases (
            tenant_id        TEXT NOT NULL,
            channel_id       TEXT NOT NULL
                             REFERENCES channels(id) ON DELETE CASCADE,
            gateway_id       TEXT NOT NULL,
            owner_lease_id   TEXT NOT NULL,
            lease_expires_at TIMESTAMPTZ NOT NULL,
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, channel_id)
        );
        CREATE INDEX IF NOT EXISTS channel_gateway_leases_expiry_idx
          ON channel_gateway_leases (tenant_id, lease_expires_at);

        ALTER TABLE channel_gateway_leases ENABLE ROW LEVEL SECURITY;
        ALTER TABLE channel_gateway_leases FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON channel_gateway_leases;
        CREATE POLICY tenant_isolation ON channel_gateway_leases
          USING (tenant_id = current_setting('app.tenant_id', true))
          WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS channel_gateway_leases;")
