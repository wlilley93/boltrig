"""Durable channel-gateway desired/observed evidence.

Revision ID: 0053_channel_gateway_reconciliation
Revises: 0052_integration_auth_contracts
"""

from __future__ import annotations

from alembic import op

revision = "0053_channel_gateway_reconciliation"
down_revision = "0052_integration_auth_contracts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS channel_gateway_status (
            tenant_id         TEXT NOT NULL,
            channel_id        TEXT NOT NULL
                              REFERENCES channels(id) ON DELETE CASCADE,
            gateway_id        TEXT NOT NULL,
            desired_revision  TEXT NOT NULL,
            observed_revision TEXT NOT NULL,
            status            TEXT NOT NULL,
            reason_code       TEXT,
            observed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, channel_id)
        );
        CREATE INDEX IF NOT EXISTS channel_gateway_status_observed_idx
          ON channel_gateway_status (tenant_id, observed_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS channel_gateway_status;")
