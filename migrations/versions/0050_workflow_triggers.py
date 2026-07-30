"""Governed webhook/channel bindings for durable workflow triggers.

Revision ID: 0050_workflow_triggers
Revises: 0049_eval_case_lifecycle
"""

from __future__ import annotations

from alembic import op

revision = "0050_workflow_triggers"
down_revision = "0049_eval_case_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_triggers (
            id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            workflow_id TEXT NOT NULL,
            workspace_id TEXT,
            name TEXT NOT NULL,
            source TEXT NOT NULL CHECK (source IN ('webhook','channel')),
            owner_id TEXT NOT NULL,
            grant_allow JSONB NOT NULL DEFAULT '[]'::jsonb,
            grant_deny JSONB NOT NULL DEFAULT '[]'::jsonb,
            channel_id TEXT REFERENCES channels(id) ON DELETE CASCADE,
            secret_hash TEXT,
            enabled BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id,id),
            UNIQUE (tenant_id,workflow_id,name),
            CONSTRAINT workflow_trigger_shape CHECK (
              (source='webhook' AND channel_id IS NULL
                AND secret_hash ~ '^[0-9a-f]{64}$')
              OR
              (source='channel' AND channel_id IS NOT NULL
                AND secret_hash IS NULL)
            ),
            CONSTRAINT workflow_trigger_grants_arrays CHECK (
              jsonb_typeof(grant_allow)='array'
              AND jsonb_typeof(grant_deny)='array'
            )
        );
        CREATE INDEX IF NOT EXISTS workflow_triggers_workflow_idx
          ON workflow_triggers(tenant_id,workflow_id,created_at,id);
        CREATE INDEX IF NOT EXISTS workflow_triggers_channel_idx
          ON workflow_triggers(tenant_id,channel_id,enabled)
          WHERE source='channel';

        CREATE TABLE IF NOT EXISTS workflow_trigger_deliveries (
            tenant_id TEXT NOT NULL,
            trigger_id TEXT NOT NULL,
            source_event_digest TEXT NOT NULL,
            status TEXT NOT NULL,
            authority_subject TEXT,
            run_id TEXT,
            hitl_request_id TEXT,
            reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id,trigger_id,source_event_digest),
            FOREIGN KEY (tenant_id,trigger_id)
              REFERENCES workflow_triggers(tenant_id,id) ON DELETE CASCADE,
            CONSTRAINT workflow_trigger_event_digest_sha256
              CHECK (source_event_digest ~ '^[0-9a-f]{64}$')
        );
        CREATE INDEX IF NOT EXISTS workflow_trigger_deliveries_recent_idx
          ON workflow_trigger_deliveries(
            tenant_id,trigger_id,created_at DESC
          );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS workflow_trigger_deliveries;
        DROP TABLE IF EXISTS workflow_triggers;
        """
    )

