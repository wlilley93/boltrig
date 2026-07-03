"""session active workspace ([2026] VJS-COUNTY 8, D4).

An ordered delta bringing an existing database up to carry the session's ACTIVE
WORKSPACE. A fresh database already gets this column from the baseline replay of
store/schema.sql; this migration is the in-place upgrade for a provisioned one.
Idempotent (ADD COLUMN IF NOT EXISTS), matching schema.sql exactly.

ADDITIVE only: it adds a nullable hint column on user_sessions. It does NOT change
how any grant is computed - the active workspace is a hint that the session
resolver RE-AUTHORIZES against workspace_members every request (fail-closed to no
active workspace), so a stale value can never confer access. Threading the
workspace scope through grant/credential/AI-key/workflow resolution is the next
phase (D11).

Adds:
  - user_sessions.active_workspace_id: the workspace the user last switched to
    (POST /v1/me/active-context) or the default resolved from membership at login;
    NULL when the user has no workspace yet. Never trusted on its own.

Revision ID: 0012_session_active_workspace
Revises: 0011_org_workspace_tenancy
"""

from __future__ import annotations

from alembic import op

revision = "0012_session_active_workspace"
down_revision = "0011_org_workspace_tenancy"
branch_labels = None
depends_on = None

_DDL = """
ALTER TABLE user_sessions ADD COLUMN IF NOT EXISTS active_workspace_id TEXT;
"""

_DOWN = """
ALTER TABLE user_sessions DROP COLUMN IF EXISTS active_workspace_id;
"""


def upgrade() -> None:
    op.execute(_DDL)


def downgrade() -> None:
    op.execute(_DOWN)
