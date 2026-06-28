"""round four: users, personal access tokens, invitations, settings, sessions.

The baseline (0001) replays the whole of store/schema.sql, so a *fresh* database
already gets these tables. This ordered delta brings an existing database that
stopped at 0001 up to the Round Four schema. The DDL is idempotent (CREATE TABLE
IF NOT EXISTS), matching store/schema.sql verbatim, so it is safe either way.

Revision ID: 0002_round_four
Revises: 0001_baseline
"""

from __future__ import annotations

from alembic import op

revision = "0002_round_four"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

_DDL = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT NOT NULL,
    tenant_id     TEXT NOT NULL,
    email         TEXT,
    display_name  TEXT,
    groups        TEXT[] NOT NULL DEFAULT '{}',
    role          TEXT NOT NULL DEFAULT 'none',
    scope         JSONB NOT NULL DEFAULT '{}'::jsonb,
    status        TEXT NOT NULL DEFAULT 'active',
    source        TEXT NOT NULL DEFAULT 'idp',
    source_group  TEXT,
    last_seen_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS users_email_idx ON users (tenant_id, email);

CREATE TABLE IF NOT EXISTS personal_access_tokens (
    id            TEXT NOT NULL,
    tenant_id     TEXT NOT NULL,
    user_id       TEXT NOT NULL,
    name          TEXT NOT NULL,
    token_hash    TEXT NOT NULL,
    scope         TEXT[] NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at    TIMESTAMPTZ,
    last_used_at  TIMESTAMPTZ,
    revoked       BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS pat_user_idx ON personal_access_tokens (tenant_id, user_id);
CREATE UNIQUE INDEX IF NOT EXISTS pat_hash_idx ON personal_access_tokens (token_hash);

CREATE TABLE IF NOT EXISTS user_invitations (
    id             TEXT NOT NULL,
    tenant_id      TEXT NOT NULL,
    email          TEXT NOT NULL,
    intended_role  TEXT NOT NULL,
    intended_scope JSONB NOT NULL DEFAULT '{}'::jsonb,
    invited_by     TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at     TIMESTAMPTZ,
    status         TEXT NOT NULL DEFAULT 'pending',
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS invitations_email_idx ON user_invitations (tenant_id, email);

CREATE TABLE IF NOT EXISTS user_settings (
    tenant_id   TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, user_id, key)
);

CREATE TABLE IF NOT EXISTS user_sessions (
    id            TEXT NOT NULL,
    tenant_id     TEXT NOT NULL,
    user_id       TEXT NOT NULL,
    client        TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ,
    revoked       BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON user_sessions (tenant_id, user_id);
"""


def upgrade() -> None:
    op.execute(_DDL)


def downgrade() -> None:
    op.execute(
        "DROP TABLE IF EXISTS user_sessions, user_settings, user_invitations, "
        "personal_access_tokens, users CASCADE"
    )
