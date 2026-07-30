"""Durable realtime-call metadata and normalized events (decision 0021).

Revision ID: 0041_realtime_calls
Revises: 0040_drop_workflow_promotions
"""

from __future__ import annotations

from alembic import op

revision = "0041_realtime_calls"
down_revision = "0040_drop_workflow_promotions"
branch_labels = None
depends_on = None

_UP = r"""
CREATE TABLE IF NOT EXISTS realtime_calls (
    id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    channel_id TEXT REFERENCES channels(id) ON DELETE SET NULL,
    status TEXT NOT NULL,
    participants JSONB NOT NULL DEFAULT '[]'::jsonb,
    tool_context JSONB NOT NULL DEFAULT '{}'::jsonb,
    provider_class TEXT NOT NULL DEFAULT 'realtime_voice',
    run_id TEXT,
    media_token_hash TEXT,
    media_token_expires_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    unavailable_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, conversation_id)
      REFERENCES conversations(tenant_id, id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS realtime_calls_owner_idx
  ON realtime_calls(tenant_id, owner_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS realtime_calls_media_claim_idx
  ON realtime_calls(tenant_id, media_token_hash)
  WHERE media_token_hash IS NOT NULL;
CREATE TABLE IF NOT EXISTS realtime_call_events (
    id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    call_id TEXT NOT NULL,
    type TEXT NOT NULL,
    participant_id TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, call_id)
      REFERENCES realtime_calls(tenant_id, id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS realtime_call_events_call_idx
  ON realtime_call_events(tenant_id, call_id, created_at, id);
DO $$
DECLARE
  table_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['realtime_calls', 'realtime_call_events']
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
DROP TABLE IF EXISTS realtime_call_events;
DROP TABLE IF EXISTS realtime_calls;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
