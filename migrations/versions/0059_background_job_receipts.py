"""Bounded background-maintenance attempt receipts.

Revision ID: 0059_background_job_receipts
Revises: 0058_ai_key_proposals
"""

from __future__ import annotations

from alembic import op

revision = "0059_background_job_receipts"
down_revision = "0058_ai_key_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS background_job_receipts (
            tenant_id                 TEXT NOT NULL,
            job_name                  TEXT NOT NULL
                                      CHECK (
                                        job_name IN ('hitl_expiry','retention')
                                      ),
            process_instance_identity TEXT NOT NULL
                                      CHECK (
                                        process_instance_identity
                                        ~ '^bjp_[a-f0-9]{24}$'
                                      ),
            interval_seconds          INTEGER NOT NULL
                                      CHECK (
                                        interval_seconds >= 1
                                        AND interval_seconds <= 604800
                                      ),
            last_attempt_at           TIMESTAMPTZ NOT NULL,
            last_success_at           TIMESTAMPTZ,
            last_failure_at           TIMESTAMPTZ,
            last_outcome              TEXT NOT NULL
                                      CHECK (
                                        last_outcome IN ('succeeded','failed')
                                      ),
            failure_code              TEXT,
            last_item_count           INTEGER NOT NULL DEFAULT 0
                                      CHECK (
                                        last_item_count >= 0
                                        AND last_item_count <= 1000000
                                      ),
            receipt_kind              TEXT NOT NULL
                                      DEFAULT 'attempt_history_not_liveness'
                                      CHECK (
                                        receipt_kind
                                        = 'attempt_history_not_liveness'
                                      ),
            PRIMARY KEY (
              tenant_id,job_name,process_instance_identity
            ),
            CONSTRAINT background_job_timestamp_shape CHECK (
              (last_success_at IS NULL OR last_success_at <= last_attempt_at)
              AND
              (last_failure_at IS NULL OR last_failure_at <= last_attempt_at)
            ),
            CONSTRAINT background_job_outcome_shape CHECK (
              (
                last_outcome='succeeded'
                AND last_success_at=last_attempt_at
                AND failure_code IS NULL
              )
              OR
              (
                last_outcome='failed'
                AND last_failure_at=last_attempt_at
                AND failure_code='sweep_failed'
              )
            )
        );
        CREATE INDEX IF NOT EXISTS background_job_receipts_attempt_idx
          ON background_job_receipts (
            tenant_id,job_name,last_attempt_at DESC
          );

        ALTER TABLE background_job_receipts ENABLE ROW LEVEL SECURITY;
        ALTER TABLE background_job_receipts FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON background_job_receipts;
        CREATE POLICY tenant_isolation ON background_job_receipts
          USING (tenant_id = current_setting('app.tenant_id', true))
          WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS background_job_receipts;")
