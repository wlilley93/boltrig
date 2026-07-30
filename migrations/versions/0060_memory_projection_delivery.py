"""Add bounded delivery evidence to memory projection receipts.

Revision ID: 0060_memory_projection_delivery
Revises: 0059_background_job_receipts
"""

from __future__ import annotations

from alembic import op

revision = "0060_memory_projection_delivery"
down_revision = "0059_background_job_receipts"
branch_labels = None
depends_on = None

_UP = """
ALTER TABLE memory_projection_statuses
    ADD COLUMN IF NOT EXISTS enqueue_attempts INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS operation_attempts INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS max_operation_attempts INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS first_attempt_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_attempt_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_failure_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS failure_code TEXT;

ALTER TABLE memory_projection_statuses
    DROP CONSTRAINT IF EXISTS memory_projection_enqueue_attempts_check,
    ADD CONSTRAINT memory_projection_enqueue_attempts_check
        CHECK (enqueue_attempts BETWEEN 0 AND 1),
    DROP CONSTRAINT IF EXISTS memory_projection_operation_attempts_check,
    ADD CONSTRAINT memory_projection_operation_attempts_check
        CHECK (
            max_operation_attempts BETWEEN 1 AND 5
            AND operation_attempts BETWEEN 0 AND max_operation_attempts
        ),
    DROP CONSTRAINT IF EXISTS memory_projection_failure_code_check,
    ADD CONSTRAINT memory_projection_failure_code_check
        CHECK (
            failure_code IS NULL OR failure_code IN (
                'enqueue_failed',
                'projection_operation_failed',
                'projection_not_configured',
                'invalid_projection_result'
            )
        );
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE memory_projection_statuses
            DROP CONSTRAINT IF EXISTS memory_projection_failure_code_check,
            DROP CONSTRAINT IF EXISTS memory_projection_operation_attempts_check,
            DROP CONSTRAINT IF EXISTS memory_projection_enqueue_attempts_check,
            DROP COLUMN IF EXISTS failure_code,
            DROP COLUMN IF EXISTS last_failure_at,
            DROP COLUMN IF EXISTS last_attempt_at,
            DROP COLUMN IF EXISTS first_attempt_at,
            DROP COLUMN IF EXISTS max_operation_attempts,
            DROP COLUMN IF EXISTS operation_attempts,
            DROP COLUMN IF EXISTS enqueue_attempts;
        """
    )
