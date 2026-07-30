"""Single-use password recovery tokens.

Revision ID: 0045_password_reset
Revises: 0044_artifacts
"""

from __future__ import annotations

from alembic import op

revision = "0045_password_reset"
down_revision = "0044_artifacts"
branch_labels = None
depends_on = None

_UP = r"""
CREATE TABLE password_reset_tokens (
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    consumed_at TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, user_id),
    CONSTRAINT password_reset_token_hash_sha256
      CHECK (token_hash ~ '^[0-9a-f]{64}$')
);
CREATE UNIQUE INDEX password_reset_token_hash_idx
  ON password_reset_tokens(token_hash);
ALTER TABLE password_reset_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE password_reset_tokens FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON password_reset_tokens
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
"""

_DOWN = "DROP TABLE IF EXISTS password_reset_tokens;"


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
