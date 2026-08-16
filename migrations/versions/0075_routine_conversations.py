"""Identify routine-created conversations without title conventions.

Revision ID: 0075_routine_conversations
Revises: 0074_conversation_steer_queue
"""

from __future__ import annotations

from alembic import op

revision = "0075_routine_conversations"
down_revision = "0074_conversation_steer_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE conversations
          ADD COLUMN origin TEXT NOT NULL DEFAULT 'user',
          ADD COLUMN source_ref TEXT,
          ADD COLUMN source_run_id TEXT,
          ADD COLUMN companion_id TEXT,
          ADD CONSTRAINT conversations_origin_check
            CHECK (origin IN ('user','routine')),
          ADD CONSTRAINT conversations_companion_id_check
            CHECK (companion_id IS NULL OR companion_id IN ('familiar','jarvis'));
        CREATE UNIQUE INDEX conversations_routine_run_idx
          ON conversations (tenant_id, source_run_id)
          WHERE origin='routine' AND source_run_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM conversations WHERE origin <> 'user') THEN
            RAISE EXCEPTION 'routine conversations still exist';
          END IF;
        END $$"""
    )
    op.execute(
        """
        DROP INDEX conversations_routine_run_idx;
        ALTER TABLE conversations
          DROP CONSTRAINT conversations_companion_id_check,
          DROP CONSTRAINT conversations_origin_check,
          DROP COLUMN companion_id,
          DROP COLUMN source_run_id,
          DROP COLUMN source_ref,
          DROP COLUMN origin;
        """
    )
