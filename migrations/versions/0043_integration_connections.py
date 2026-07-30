"""Reviewed integration catalogue and tenant connection state.

Revision ID: 0043_integration_connections
Revises: 0042_desktop_devices
"""

from __future__ import annotations

from alembic import op

revision = "0043_integration_connections"
down_revision = "0042_desktop_devices"
branch_labels = None
depends_on = None

_UP = r"""
CREATE TABLE IF NOT EXISTS integration_catalogue (
    id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    label TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN (
      'communications','work','storage_design','crm_sales','finance',
      'analytics_operations','browser')),
    transport TEXT NOT NULL CHECK (transport IN (
      'rest','mcp','channel_gateway','browser')),
    auth JSONB NOT NULL DEFAULT '[]'::jsonb,
    description TEXT NOT NULL,
    certification TEXT NOT NULL DEFAULT 'uncertified' CHECK (certification IN (
      'uncertified','certifying','certified','suspended')),
    adapter_id TEXT,
    setup_copy TEXT,
    access_copy TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE TABLE IF NOT EXISTS integration_connections (
    id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    integration_id TEXT NOT NULL,
    adapter_id TEXT NOT NULL,
    label TEXT NOT NULL,
    health TEXT NOT NULL DEFAULT 'pending' CHECK (health IN (
      'pending','ok','degraded','down','revoked')),
    credential_ref TEXT,
    credential_owned BOOLEAN NOT NULL DEFAULT false,
    accounts JSONB NOT NULL DEFAULT '[]'::jsonb,
    last_checked_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, integration_id)
      REFERENCES integration_catalogue(tenant_id, id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS integration_connections_integration_idx
  ON integration_connections(tenant_id, integration_id, created_at);
DO $$
DECLARE
  table_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'integration_catalogue', 'integration_connections'
  ]
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', table_name);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON %I '
      'USING (tenant_id = current_setting(''app.tenant_id'', true)) '
      'WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))',
      table_name
    );
  END LOOP;
END
$$;
"""

_DOWN = """
DROP TABLE IF EXISTS integration_connections;
DROP TABLE IF EXISTS integration_catalogue;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
