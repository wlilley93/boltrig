"""Persist external MCP lifecycle, safe tool snapshots, and probe receipts.

Revision ID: 0063_mcp_lifecycle_receipts
Revises: 0062_channel_gateway_owner_leases
"""

from __future__ import annotations

from alembic import op

revision = "0063_mcp_lifecycle_receipts"
down_revision = "0062_channel_gateway_owner_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE mcp_servers
          ALTER COLUMN url DROP NOT NULL,
          ALTER COLUMN transport DROP NOT NULL,
          ALTER COLUMN status DROP DEFAULT;

        UPDATE mcp_servers
           SET status = CASE
             WHEN status = 'active' THEN 'active'
             ELSE 'inactive'
           END;

        ALTER TABLE mcp_servers
          ALTER COLUMN status SET DEFAULT 'inactive',
          ADD COLUMN IF NOT EXISTS last_known_tools JSONB
            NOT NULL DEFAULT '[]'::jsonb,
          ADD COLUMN IF NOT EXISTS tools_observed_at TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS retired_at TIMESTAMPTZ,
          ADD CONSTRAINT mcp_servers_status_check
            CHECK (status IN ('inactive', 'active', 'retired')),
          ADD CONSTRAINT mcp_servers_retired_at_check
            CHECK (
              (status = 'retired' AND retired_at IS NOT NULL)
              OR (status <> 'retired' AND retired_at IS NULL)
            ),
          ADD CONSTRAINT mcp_servers_tools_array_check
            CHECK (jsonb_typeof(last_known_tools) = 'array');

        CREATE INDEX IF NOT EXISTS mcp_servers_lifecycle_idx
          ON mcp_servers (tenant_id, status, id);

        INSERT INTO mcp_servers
          (id, tenant_id, status, created_at, updated_at)
        SELECT
          id, tenant_id,
          CASE WHEN activated THEN 'active' ELSE 'inactive' END,
          created_at, updated_at
        FROM adapters
        WHERE module_ref = 'boltrig.adapters.mcp_consumer'
        ON CONFLICT (tenant_id, id) DO UPDATE SET
          status = EXCLUDED.status,
          retired_at = NULL,
          updated_at = GREATEST(mcp_servers.updated_at, EXCLUDED.updated_at);

        DELETE FROM mcp_servers m
        WHERE NOT EXISTS (
          SELECT 1 FROM adapters a
          WHERE a.tenant_id = m.tenant_id
            AND a.id = m.id
            AND a.module_ref = 'boltrig.adapters.mcp_consumer'
        );

        ALTER TABLE mcp_servers
          ADD CONSTRAINT mcp_servers_adapter_fkey
          FOREIGN KEY (tenant_id, id) REFERENCES adapters(tenant_id, id)
          ON DELETE CASCADE;

        CREATE TABLE IF NOT EXISTS mcp_probe_receipts (
            tenant_id   TEXT NOT NULL,
            server_id   TEXT NOT NULL,
            probe_id    TEXT NOT NULL,
            outcome     TEXT NOT NULL
                        CHECK (outcome IN ('succeeded', 'failed')),
            failure_code TEXT CHECK (
              failure_code IS NULL OR failure_code IN (
                'credential_unavailable', 'egress_denied',
                'transport_unavailable', 'protocol_invalid',
                'discovery_invalid', 'unexpected_failure'
              )
            ),
            observed_at TIMESTAMPTZ NOT NULL,
            tool_count  INTEGER NOT NULL
                        CHECK (tool_count BETWEEN 0 AND 500),
            receipt_kind TEXT NOT NULL DEFAULT 'content_free_probe_attempt'
                         CHECK (receipt_kind = 'content_free_probe_attempt'),
            CHECK (
              (outcome = 'succeeded' AND failure_code IS NULL)
              OR (outcome = 'failed' AND failure_code IS NOT NULL)
            ),
            PRIMARY KEY (tenant_id, server_id, probe_id),
            FOREIGN KEY (tenant_id, server_id)
              REFERENCES mcp_servers(tenant_id, id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS mcp_probe_receipts_recent_idx
          ON mcp_probe_receipts
             (tenant_id, server_id, observed_at DESC, probe_id DESC);

        ALTER TABLE mcp_probe_receipts ENABLE ROW LEVEL SECURITY;
        ALTER TABLE mcp_probe_receipts FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON mcp_probe_receipts;
        CREATE POLICY tenant_isolation ON mcp_probe_receipts
          USING (tenant_id = current_setting('app.tenant_id', true))
          WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS mcp_probe_receipts;
        DROP INDEX IF EXISTS mcp_servers_lifecycle_idx;
        ALTER TABLE mcp_servers
          DROP CONSTRAINT IF EXISTS mcp_servers_adapter_fkey,
          DROP CONSTRAINT IF EXISTS mcp_servers_tools_array_check,
          DROP CONSTRAINT IF EXISTS mcp_servers_retired_at_check,
          DROP CONSTRAINT IF EXISTS mcp_servers_status_check,
          DROP COLUMN IF EXISTS retired_at,
          DROP COLUMN IF EXISTS tools_observed_at,
          DROP COLUMN IF EXISTS last_known_tools,
          ALTER COLUMN status SET DEFAULT 'pending_review';
        """
    )
