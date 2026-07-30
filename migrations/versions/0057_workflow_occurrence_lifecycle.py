"""Workflow schedule occurrence observation and exact retry lifecycle.

Revision ID: 0057_workflow_occurrence_lifecycle
Revises: 0056_birth_profile_receipts
"""

from __future__ import annotations

from alembic import op

revision = "0057_workflow_occurrence_lifecycle"
down_revision = "0056_birth_profile_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE workflow_schedule_occurrences
          DROP CONSTRAINT workflow_schedule_occurrences_status_check;
        ALTER TABLE workflow_schedule_occurrences
          ADD CONSTRAINT workflow_schedule_occurrences_status_check
          CHECK (status IN (
            'claimed','retryable','queued','succeeded','failed'
          ));

        ALTER TABLE workflow_schedule_occurrences
          ADD COLUMN workflow_sha256 TEXT,
          ADD COLUMN schedule_sha256 TEXT,
          ADD COLUMN claimed_at TIMESTAMPTZ,
          ADD COLUMN enqueued_at TIMESTAMPTZ,
          ADD COLUMN outcome_at TIMESTAMPTZ,
          ADD COLUMN manual_retries INTEGER NOT NULL DEFAULT 0,
          ADD COLUMN last_retry_at TIMESTAMPTZ;

        ALTER TABLE workflow_schedule_occurrences
          ADD CONSTRAINT workflow_schedule_occurrence_manual_retries
          CHECK (manual_retries >= 0);

        UPDATE workflow_schedule_occurrences
           SET claimed_at=created_at,
               enqueued_at=CASE WHEN status='queued' THEN updated_at END,
               outcome_at=CASE WHEN status='failed' THEN updated_at END;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE workflow_schedule_occurrences
           SET status='queued'
         WHERE status='succeeded';

        ALTER TABLE workflow_schedule_occurrences
          DROP CONSTRAINT workflow_schedule_occurrence_manual_retries;
        ALTER TABLE workflow_schedule_occurrences
          DROP COLUMN last_retry_at,
          DROP COLUMN manual_retries,
          DROP COLUMN outcome_at,
          DROP COLUMN enqueued_at,
          DROP COLUMN claimed_at,
          DROP COLUMN schedule_sha256,
          DROP COLUMN workflow_sha256;

        ALTER TABLE workflow_schedule_occurrences
          DROP CONSTRAINT workflow_schedule_occurrences_status_check;
        ALTER TABLE workflow_schedule_occurrences
          ADD CONSTRAINT workflow_schedule_occurrences_status_check
          CHECK (status IN ('claimed','retryable','queued','failed'));
        """
    )
