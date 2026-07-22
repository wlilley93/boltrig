"""Channel gateway Phase-2 durability: intake dedup markers + the socket-class
outbound hand-off (decision 0003).

Revision ID: 0035_channel_durability
Revises: 0034_knowledge_fabric
"""

from __future__ import annotations

from alembic import op

revision = "0035_channel_durability"
down_revision = "0034_knowledge_fabric"
branch_labels = None
depends_on = None

# Row-level tenant isolation for both tables is applied by the shared rls.sql
# replay (which now lists them), matching channel_bindings / channel_pairings.
DDL = r"""
CREATE TABLE IF NOT EXISTS channel_deliveries (
    tenant_id TEXT NOT NULL,
    channel_id TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    delivery_id TEXT NOT NULL,
    seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, channel_id, delivery_id)
);
CREATE INDEX IF NOT EXISTS channel_deliveries_expiry_idx
  ON channel_deliveries(tenant_id,expires_at);
CREATE TABLE IF NOT EXISTS channel_outbox (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL,
    channel_id TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INT NOT NULL DEFAULT 0,
    lease_owner TEXT, lease_expires_at TIMESTAMPTZ, next_attempt_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (tenant_id,id)
);
CREATE INDEX IF NOT EXISTS channel_outbox_claim_idx
  ON channel_outbox(tenant_id,channel_id,status,created_at);
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS channel_outbox;
        DROP TABLE IF EXISTS channel_deliveries;
        """
    )
