"""TOTP two-factor + one-time recovery codes ([2026] VJS-COUNTY 10).

An ordered delta bringing an existing database up to carry the console second
factor. A fresh database already gets these from the baseline replay of
store/schema.sql; this migration is the in-place upgrade for a provisioned one.
Idempotent (CREATE TABLE IF NOT EXISTS), matching schema.sql.

Adds three tables, all kept apart from the users identity row (like
user_credentials) so no 2FA secret rides in a user view/export:

  - user_totp: the enrolment row. The base32 TOTP shared secret is NOT stored
    here - it is SEALED in credential_refs and referenced by secret_ref (D1). Only
    the ref + the enrolled flag live here.
  - user_recovery_codes: one-time recovery codes stored ONLY as sha256 hashes (D2),
    each single-use (used_at flips once).
  - two_factor_challenges: the pending pre-session login challenge (D3) - a
    short-lived, single-use token (stored as its sha256) that carries no access on
    its own and only lets a follow-up factor verify issue the session.

Row-level tenant isolation for the three new tables is applied by the shared
rls.sql replay (which now lists them), matching the sibling access tables - not
inline in the migration.

Revision ID: 0018_totp_two_factor
Revises: 0017_ai_config_base_url
"""

from __future__ import annotations

from alembic import op

revision = "0018_totp_two_factor"
down_revision = "0017_ai_config_base_url"
branch_labels = None
depends_on = None

_DDL = """
CREATE TABLE IF NOT EXISTS user_totp (
    tenant_id   TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    secret_ref  TEXT NOT NULL,
    enrolled    BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, user_id)
);

CREATE TABLE IF NOT EXISTS user_recovery_codes (
    tenant_id   TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    code_hash   TEXT NOT NULL,
    used_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, user_id, code_hash)
);

CREATE TABLE IF NOT EXISTS two_factor_challenges (
    tenant_id   TEXT NOT NULL,
    token_hash  TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, token_hash)
);
CREATE INDEX IF NOT EXISTS tfa_challenges_user_idx
    ON two_factor_challenges (tenant_id, user_id);
"""

_DOWN = """
DROP INDEX IF EXISTS tfa_challenges_user_idx;
DROP TABLE IF EXISTS two_factor_challenges;
DROP TABLE IF EXISTS user_recovery_codes;
DROP TABLE IF EXISTS user_totp;
"""


def upgrade() -> None:
    op.execute(_DDL)


def downgrade() -> None:
    op.execute(_DOWN)
