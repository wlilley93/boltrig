"""Durable workflow schedule desired state and occurrence receipts.

Revision ID: 0055_workflow_schedules
Revises: 0054_permanent_fleet_observations
"""

from __future__ import annotations

from alembic import op

revision = "0055_workflow_schedules"
down_revision = "0054_permanent_fleet_observations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_schedules (
            tenant_id          TEXT NOT NULL,
            workflow_id        TEXT NOT NULL,
            workspace_id       TEXT,
            cron               TEXT NOT NULL,
            timezone           TEXT NOT NULL,
            authority_subject  TEXT,
            grant_allow        JSONB NOT NULL DEFAULT '[]'::jsonb,
            grant_deny         JSONB NOT NULL DEFAULT '[]'::jsonb,
            observed_status    TEXT NOT NULL DEFAULT 'pending'
                               CHECK (observed_status IN (
                                 'pending','active','needs_action',
                                 'unavailable','degraded'
                               )),
            observed_reason    TEXT,
            next_due_at        TIMESTAMPTZ,
            last_scheduled_for TIMESTAMPTZ,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            observed_at        TIMESTAMPTZ,
            PRIMARY KEY (tenant_id,workflow_id),
            CONSTRAINT workflow_schedule_grants_arrays CHECK (
              jsonb_typeof(grant_allow)='array'
              AND jsonb_typeof(grant_deny)='array'
            )
        );
        CREATE INDEX IF NOT EXISTS workflow_schedules_due_idx
          ON workflow_schedules(tenant_id,next_due_at,workflow_id);

        CREATE TABLE IF NOT EXISTS workflow_schedule_occurrences (
            tenant_id       TEXT NOT NULL,
            workflow_id     TEXT NOT NULL,
            scheduled_for   TIMESTAMPTZ NOT NULL,
            run_id          TEXT NOT NULL,
            status          TEXT NOT NULL CHECK (status IN (
                              'claimed','retryable','queued','failed'
                            )),
            lease_owner     TEXT,
            lease_expires_at TIMESTAMPTZ,
            engine_run_id   TEXT,
            reason          TEXT,
            attempts        INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id,workflow_id,scheduled_for),
            UNIQUE (tenant_id,run_id),
            CONSTRAINT workflow_schedule_occurrence_lease_shape CHECK (
              (status='claimed' AND lease_owner IS NOT NULL
                                AND lease_expires_at IS NOT NULL)
              OR
              (status<>'claimed' AND lease_owner IS NULL
                                 AND lease_expires_at IS NULL)
            )
        );
        CREATE INDEX IF NOT EXISTS workflow_schedule_occurrences_claim_idx
          ON workflow_schedule_occurrences(
            tenant_id,status,lease_expires_at,scheduled_for
          );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS workflow_schedule_occurrences;
        DROP TABLE IF EXISTS workflow_schedules;
        """
    )
