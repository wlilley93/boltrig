"""Flat named-agent federation: identities, mailboxes, and logical sessions.

Every named agent is a durable tier-1 peer.  The message envelope is immutable;
mutable claim/retry state lives in a separate delivery table.  A per-identity
turn scheduler serializes interactive, peer, and background wakes across worker replicas, while logical sessions
and append-only summaries preserve continuity without requiring one permanent
model process.  Ephemeral children have no identity row and therefore cannot be
addressed.

Revision ID: 0084_named_agent_mailboxes
Revises: 0083_agent_capability_workspace_scope
"""

from __future__ import annotations

from alembic import op

revision = "0084_named_agent_mailboxes"
down_revision = "0083_agent_capability_workspace_scope"
branch_labels = None
depends_on = None


TABLES = """
CREATE TABLE IF NOT EXISTS named_agents (
    tenant_id          TEXT NOT NULL,
    address            TEXT NOT NULL,
    name               TEXT NOT NULL,
    runtime            TEXT NOT NULL,
    model_endpoint     TEXT,
    supported_skills   TEXT[] NOT NULL DEFAULT ARRAY['*']::TEXT[],
    max_depth          INTEGER NOT NULL DEFAULT 3,
    cost_tier          TEXT NOT NULL DEFAULT 'standard',
    purpose            TEXT NOT NULL DEFAULT '',
    brief              TEXT NOT NULL DEFAULT '',
    scope_id           TEXT,
    default_for_intake BOOLEAN NOT NULL DEFAULT FALSE,
    enabled            BOOLEAN NOT NULL DEFAULT TRUE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,address),
    UNIQUE (tenant_id,name),
    CHECK (address ~ '^[a-z0-9][a-z0-9_-]{0,62}$'),
    CHECK (scope_id IS NULL OR scope_id ~ '^[a-z0-9][a-z0-9_-]{0,62}$'),
    CHECK (runtime IN ('codex','script','python-script')),
    CHECK (max_depth BETWEEN 1 AND 5),
    CHECK (cardinality(supported_skills) BETWEEN 1 AND 64),
    CHECK (octet_length(purpose) <= 2000),
    CHECK (octet_length(brief) <= 32000)
);
CREATE UNIQUE INDEX IF NOT EXISTS named_agents_one_default_idx
  ON named_agents(tenant_id) WHERE default_for_intake AND enabled;

ALTER TABLE conversations ADD COLUMN IF NOT EXISTS agent_address TEXT;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS workspace_id TEXT;
ALTER TABLE conversation_messages
  ADD COLUMN IF NOT EXISTS recipient_agent_address TEXT;
ALTER TABLE conversation_messages
  ADD COLUMN IF NOT EXISTS author_agent_address TEXT;
CREATE INDEX IF NOT EXISTS conversations_agent_idx
  ON conversations(tenant_id,agent_address,updated_at DESC);
CREATE INDEX IF NOT EXISTS conversations_workspace_idx
  ON conversations(tenant_id,workspace_id,updated_at DESC);
DO $$
BEGIN
  ALTER TABLE conversations
    ADD CONSTRAINT conversations_named_agent_fkey
    FOREIGN KEY (tenant_id,agent_address)
    REFERENCES named_agents(tenant_id,address) ON DELETE RESTRICT;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
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

CREATE TABLE IF NOT EXISTS agent_turn_leases (
    tenant_id       TEXT NOT NULL,
    agent_address   TEXT NOT NULL,
    lease_owner     TEXT,
    lease_token     TEXT,
    lane            TEXT,
    lease_expires_at TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,agent_address),
    FOREIGN KEY (tenant_id,agent_address)
      REFERENCES named_agents(tenant_id,address) ON DELETE CASCADE,
    CHECK (lane IS NULL OR lane IN ('interactive','peer','background')),
    CHECK (
      (lease_owner IS NULL AND lease_token IS NULL AND lane IS NULL
       AND lease_expires_at IS NULL)
      OR
      (lease_owner IS NOT NULL AND lease_token IS NOT NULL AND lane IS NOT NULL
       AND lease_expires_at IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS agent_turn_waiters (
    tenant_id       TEXT NOT NULL,
    agent_address   TEXT NOT NULL,
    waiter_id       TEXT NOT NULL,
    lane            TEXT NOT NULL,
    requested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id,agent_address,waiter_id),
    FOREIGN KEY (tenant_id,agent_address)
      REFERENCES named_agents(tenant_id,address) ON DELETE CASCADE,
    CHECK (lane IN ('interactive','peer','background'))
);
CREATE INDEX IF NOT EXISTS agent_turn_waiters_schedule_idx
  ON agent_turn_waiters(tenant_id,agent_address,lane,requested_at,waiter_id);

CREATE TABLE IF NOT EXISTS agent_sessions (
    id              TEXT NOT NULL,
    tenant_id       TEXT NOT NULL,
    agent_address   TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,id),
    UNIQUE (tenant_id,agent_address,conversation_id),
    FOREIGN KEY (tenant_id,agent_address)
      REFERENCES named_agents(tenant_id,address) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS agent_messages (
    id              TEXT NOT NULL,
    tenant_id       TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    sender          TEXT NOT NULL,
    recipient       TEXT NOT NULL,
    kind            TEXT NOT NULL,
    content         TEXT NOT NULL,
    reply_to        TEXT,
    correlation_id  TEXT,
    run_id          TEXT,
    authority       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,id),
    FOREIGN KEY (tenant_id,sender)
      REFERENCES named_agents(tenant_id,address) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,recipient)
      REFERENCES named_agents(tenant_id,address) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,reply_to)
      REFERENCES agent_messages(tenant_id,id) ON DELETE RESTRICT,
    CHECK (sender <> recipient),
    CHECK (kind IN ('ask','tell','reply')),
    CHECK (octet_length(content) BETWEEN 1 AND 32768),
    CHECK (jsonb_typeof(authority)='object')
);
CREATE INDEX IF NOT EXISTS agent_messages_conversation_idx
  ON agent_messages(tenant_id,conversation_id,created_at,id);
CREATE INDEX IF NOT EXISTS agent_messages_recipient_idx
  ON agent_messages(tenant_id,recipient,created_at,id);

CREATE TABLE IF NOT EXISTS agent_message_deliveries (
    tenant_id       TEXT NOT NULL,
    message_id      TEXT NOT NULL,
    recipient       TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    attempts        INTEGER NOT NULL DEFAULT 0,
    lease_owner     TEXT,
    lease_expires_at TIMESTAMPTZ,
    available_at    TIMESTAMPTZ,
    last_error      TEXT,
    delivered_at    TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,message_id),
    FOREIGN KEY (tenant_id,message_id)
      REFERENCES agent_messages(tenant_id,id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,recipient)
      REFERENCES named_agents(tenant_id,address) ON DELETE RESTRICT,
    CHECK (status IN ('pending','in_flight','delivered','failed')),
    CHECK (attempts >= 0),
    CHECK ((lease_owner IS NULL) = (lease_expires_at IS NULL))
);
CREATE INDEX IF NOT EXISTS agent_deliveries_claim_idx
  ON agent_message_deliveries(tenant_id,recipient,status,available_at,updated_at);

CREATE TABLE IF NOT EXISTS agent_session_summaries (
    id               TEXT NOT NULL,
    tenant_id        TEXT NOT NULL,
    session_id       TEXT NOT NULL,
    up_to_message_id TEXT NOT NULL,
    covered_count    INTEGER NOT NULL,
    summary          TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,id),
    FOREIGN KEY (tenant_id,session_id)
      REFERENCES agent_sessions(tenant_id,id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,up_to_message_id)
      REFERENCES agent_messages(tenant_id,id) ON DELETE RESTRICT,
    CHECK (covered_count > 0),
    CHECK (octet_length(summary) <= 16384)
);
CREATE INDEX IF NOT EXISTS agent_session_summaries_latest_idx
  ON agent_session_summaries(tenant_id,session_id,covered_count DESC,created_at DESC);
"""


def upgrade() -> None:
    op.execute(TABLES)


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE conversations
          DROP CONSTRAINT IF EXISTS conversations_named_agent_fkey;
        ALTER TABLE conversations
          DROP CONSTRAINT IF EXISTS conversations_workspace_fkey;
        ALTER TABLE conversation_messages
          DROP CONSTRAINT IF EXISTS conversation_messages_recipient_agent_fkey;
        ALTER TABLE conversation_messages
          DROP CONSTRAINT IF EXISTS conversation_messages_author_agent_fkey;
        DROP INDEX IF EXISTS conversations_agent_idx;
        DROP INDEX IF EXISTS conversations_workspace_idx;
        ALTER TABLE conversation_messages
          DROP COLUMN IF EXISTS author_agent_address;
        ALTER TABLE conversation_messages
          DROP COLUMN IF EXISTS recipient_agent_address;
        ALTER TABLE conversations DROP COLUMN IF EXISTS workspace_id;
        ALTER TABLE conversations DROP COLUMN IF EXISTS agent_address;
        DROP TABLE IF EXISTS agent_session_summaries;
        DROP TABLE IF EXISTS agent_message_deliveries;
        DROP TABLE IF EXISTS agent_messages;
        DROP TABLE IF EXISTS agent_sessions;
        DROP TABLE IF EXISTS agent_turn_waiters;
        DROP TABLE IF EXISTS agent_turn_leases;
        DROP TABLE IF EXISTS named_agents;
        """
    )
