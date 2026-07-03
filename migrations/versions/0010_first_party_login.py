"""first-party invite-only login ([2026] VJS-COUNTY 7).

An ordered delta bringing an existing database up to carry the first-party
email/password login that replaces the Cloudflare Access edge as the sole
internet-facing gate. A fresh database already gets these from the baseline
replay of store/schema.sql; this migration is the in-place upgrade for a
provisioned one. Idempotent (ADD COLUMN / CREATE TABLE IF NOT EXISTS), matching
schema.sql.

Adds:
  - user_invitations.token_hash: the sha256 of a single-use, expiring invite-token
    secret (D1). The secret is shown once at invite creation and never stored; a
    partial UNIQUE index enforces uniqueness only where a token exists.
  - user_credentials: the argon2id password hash (D4) kept in its OWN table, apart
    from the users identity row, so the hash never rides in a user view/export.
    Stores ONLY the PHC-encoded hash (which embeds the per-user salt).
  - user_sessions.token_hash / expires_at / csrf_token: the first-party session
    (D2/D6) - the sha256 of the cookie secret, a bounded expiry, and the
    session-bound CSRF token.

Row-level tenant isolation for the new user_credentials table is applied by the
shared rls.sql replay (which now lists it), matching the sibling access tables -
not inline in the migration.

Revision ID: 0010_first_party_login
Revises: 0009_conversation_summaries
"""

from __future__ import annotations

from alembic import op

revision = "0010_first_party_login"
down_revision = "0009_conversation_summaries"
branch_labels = None
depends_on = None

_DDL = """
ALTER TABLE user_invitations ADD COLUMN IF NOT EXISTS token_hash TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS invitations_token_hash_idx
    ON user_invitations (token_hash) WHERE token_hash IS NOT NULL;

CREATE TABLE IF NOT EXISTS user_credentials (
    tenant_id     TEXT NOT NULL,
    user_id       TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, user_id)
);

ALTER TABLE user_sessions ADD COLUMN IF NOT EXISTS token_hash TEXT;
ALTER TABLE user_sessions ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;
ALTER TABLE user_sessions ADD COLUMN IF NOT EXISTS csrf_token TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS sessions_token_hash_idx
    ON user_sessions (token_hash) WHERE token_hash IS NOT NULL;
"""

_DOWN = """
DROP INDEX IF EXISTS sessions_token_hash_idx;
ALTER TABLE user_sessions DROP COLUMN IF EXISTS csrf_token;
ALTER TABLE user_sessions DROP COLUMN IF EXISTS expires_at;
ALTER TABLE user_sessions DROP COLUMN IF EXISTS token_hash;
DROP TABLE IF EXISTS user_credentials;
DROP INDEX IF EXISTS invitations_token_hash_idx;
ALTER TABLE user_invitations DROP COLUMN IF EXISTS token_hash;
"""


def upgrade() -> None:
    op.execute(_DDL)


def downgrade() -> None:
    op.execute(_DOWN)
