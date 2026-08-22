"""Conversation addressing: workspace pinning + per-message agent attribution.

Revision ID: 0086_conversation_addressing
Revises: 0085_run_effect_ledger

This DDL first shipped as an IN-PLACE EDIT of 0084_named_agent_mailboxes on the
turn-scoped-agent-chat branch. That shape deploys nowhere: every database that
had already run 0084 (all four stacks, since v0.4.34) records the revision as
applied and never receives these columns, and the row mappers then throw on
every conversation/message read - a boot-to-outage this repo has hit before
(editing-an-applied-migration-blocks-boot). 0084 is restored to what shipped
and the additions live here, after 0085 (the run-effect ledger), which had
already claimed the next number.

The FKs are ON DELETE RESTRICT against named_agents/workspaces; no hard-delete
path exists for either today, so they constrain writes without adding a
deletion hazard.
"""

from __future__ import annotations

from alembic import op

revision = "0086_conversation_addressing"
down_revision = "0085_run_effect_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS workspace_id TEXT;
ALTER TABLE conversation_messages
  ADD COLUMN IF NOT EXISTS recipient_agent_address TEXT;
ALTER TABLE conversation_messages
  ADD COLUMN IF NOT EXISTS author_agent_address TEXT;
CREATE INDEX IF NOT EXISTS conversations_workspace_idx
  ON conversations(tenant_id,workspace_id,updated_at DESC);
DO $$
BEGIN
  ALTER TABLE conversations
    ADD CONSTRAINT conversations_workspace_fkey
    FOREIGN KEY (tenant_id,workspace_id)
    REFERENCES workspaces(tenant_id,id) ON DELETE RESTRICT;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$
BEGIN
  ALTER TABLE conversation_messages
    ADD CONSTRAINT conversation_messages_recipient_agent_fkey
    FOREIGN KEY (tenant_id,recipient_agent_address)
    REFERENCES named_agents(tenant_id,address) ON DELETE RESTRICT;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$
BEGIN
  ALTER TABLE conversation_messages
    ADD CONSTRAINT conversation_messages_author_agent_fkey
    FOREIGN KEY (tenant_id,author_agent_address)
    REFERENCES named_agents(tenant_id,address) ON DELETE RESTRICT;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
ALTER TABLE conversations
  DROP CONSTRAINT IF EXISTS conversations_workspace_fkey;
ALTER TABLE conversation_messages
  DROP CONSTRAINT IF EXISTS conversation_messages_recipient_agent_fkey;
ALTER TABLE conversation_messages
  DROP CONSTRAINT IF EXISTS conversation_messages_author_agent_fkey;
DROP INDEX IF EXISTS conversations_workspace_idx;
ALTER TABLE conversation_messages
  DROP COLUMN IF EXISTS author_agent_address;
ALTER TABLE conversation_messages
  DROP COLUMN IF EXISTS recipient_agent_address;
ALTER TABLE conversations DROP COLUMN IF EXISTS workspace_id;
        """
    )
