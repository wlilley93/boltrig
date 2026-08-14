"""Add durable ordering and claim state for queued chat steers.

Revision ID: 0074_conversation_steer_queue
Revises: 0073_agent_model_routes
"""

from __future__ import annotations

from alembic import op

revision = "0074_conversation_steer_queue"
down_revision = "0073_agent_model_routes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE conversation_steer_queue (
          tenant_id       TEXT NOT NULL,
          conversation_id TEXT NOT NULL,
          message_id      TEXT NOT NULL,
          queue_position  BIGINT NOT NULL CHECK (queue_position > 0),
          claimed_run_id  TEXT,
          enqueued_at     TIMESTAMPTZ NOT NULL,
          claimed_at      TIMESTAMPTZ,
          PRIMARY KEY (tenant_id, message_id),
          FOREIGN KEY (tenant_id, conversation_id)
            REFERENCES conversations(tenant_id, id) ON DELETE CASCADE,
          FOREIGN KEY (tenant_id, message_id)
            REFERENCES conversation_messages(tenant_id, id) ON DELETE CASCADE,
          CHECK ((claimed_run_id IS NULL) = (claimed_at IS NULL))
        );
        CREATE INDEX conversation_steer_queue_pending_idx
          ON conversation_steer_queue
          (tenant_id, conversation_id, queue_position, enqueued_at, message_id)
          WHERE claimed_run_id IS NULL;

        WITH live_assistant_counts AS (
          SELECT tenant_id, conversation_id, COUNT(*) AS answered
          FROM conversation_messages
          WHERE role='assistant' AND superseded_by IS NULL
          GROUP BY tenant_id, conversation_id
        ), ranked_users AS (
          SELECT message.tenant_id, message.conversation_id, message.id,
                 message.created_at, message.run_id,
                 ROW_NUMBER() OVER (
                   PARTITION BY message.tenant_id, message.conversation_id
                   ORDER BY message.created_at, message.id
                 ) AS user_number
          FROM conversation_messages AS message
          WHERE message.role='user' AND message.superseded_by IS NULL
        ), pending AS (
          SELECT users.*,
                 ROW_NUMBER() OVER (
                   PARTITION BY users.tenant_id, users.conversation_id
                   ORDER BY users.created_at, users.id
                 ) AS queue_position
          FROM ranked_users AS users
          LEFT JOIN live_assistant_counts AS counts
            ON counts.tenant_id=users.tenant_id
           AND counts.conversation_id=users.conversation_id
          WHERE users.user_number > COALESCE(counts.answered, 0)
            AND users.run_id IS NULL
        )
        INSERT INTO conversation_steer_queue
          (tenant_id, conversation_id, message_id, queue_position, enqueued_at)
        SELECT tenant_id, conversation_id, id, queue_position, created_at
        FROM pending;

        ALTER TABLE conversation_steer_queue ENABLE ROW LEVEL SECURITY;
        ALTER TABLE conversation_steer_queue FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON conversation_steer_queue
          USING (tenant_id = current_setting('app.tenant_id', true))
          WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
        """
    )


def downgrade() -> None:
    # A downgrade would discard user-selected order and durable claim receipts.
    op.execute(
        """DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM conversation_steer_queue) THEN
            RAISE EXCEPTION 'conversation steer queue state still exists';
          END IF;
        END $$"""
    )
    op.execute("DROP TABLE conversation_steer_queue")
