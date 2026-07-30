"""Permanent fleet desired/observed generation evidence.

Revision ID: 0054_permanent_fleet_observations
Revises: 0053_channel_gateway_reconciliation
"""

from __future__ import annotations

from alembic import op

revision = "0054_permanent_fleet_observations"
down_revision = "0053_channel_gateway_reconciliation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS permanent_fleet_observations (
            tenant_id       TEXT NOT NULL,
            worker_id       TEXT NOT NULL
                            CHECK (worker_id ~ '^[A-Za-z0-9._:-]{1,128}$'),
            generation      TEXT NOT NULL
                            CHECK (generation ~ '^pf_[a-f0-9]{24}$'),
            status          TEXT NOT NULL CHECK (status IN ('applied','degraded')),
            apply_mode      TEXT NOT NULL DEFAULT 'startup_snapshot'
                            CHECK (apply_mode = 'startup_snapshot'),
            applied_fields  JSONB NOT NULL DEFAULT '[]'::jsonb,
            inactive_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
            observed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, worker_id),
            CONSTRAINT permanent_fleet_observation_array_shape CHECK (
              jsonb_typeof(applied_fields) = 'array'
              AND jsonb_typeof(inactive_fields) = 'array'
            )
        );
        CREATE INDEX IF NOT EXISTS permanent_fleet_observed_idx
          ON permanent_fleet_observations (tenant_id, observed_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS permanent_fleet_observations;")
