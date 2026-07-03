"""Cross-tenant identity ([2026] VJS-COUNTY 11).

An ordered delta bringing an existing database up to carry cross-tenant identity:
one email is an identity that can belong to several orgs, authenticating ONCE
against a shared credential + 2FA (held at the identity realm) and then switching
its ACTIVE org (tenant). A fresh database already gets these from the baseline
replay of store/schema.sql; this migration is the in-place upgrade for a
provisioned one. Idempotent, matching schema.sql.

Adds:

  - user_sessions.active_org_id: the session's ACTIVE org (the ONE active tenant,
    D2/D3). A nullable HINT re-authorized against org_members every request, never
    trusted from the client. Additive - a legacy session leaves it NULL and the
    resolver falls back to the session's own tenant (backward-compatible).

  - identity_orgs: the global email -> orgs membership INDEX (D1). The pre-tenant
    lookup login reads to learn which orgs an email belongs to BEFORE any tenant is
    bound. DELIBERATELY RLS-EXCLUDED (like personal_access_tokens + channels): it is
    resolved by the normalised email (identity), holds no secret + no business data
    (only membership pointers), and is never the authority - every access decision
    re-checks the RLS-fenced org_members row for the bound tenant. Kept in lockstep
    with org_members by the store's add/remove_org_member.

Revision ID: 0019_cross_tenant_identity
Revises: 0018_totp_two_factor
"""

from __future__ import annotations

from alembic import op

revision = "0019_cross_tenant_identity"
down_revision = "0018_totp_two_factor"
branch_labels = None
depends_on = None

_DDL = """
ALTER TABLE user_sessions ADD COLUMN IF NOT EXISTS active_org_id TEXT;

CREATE TABLE IF NOT EXISTS identity_orgs (
    email       TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'member',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (email, tenant_id)
);
CREATE INDEX IF NOT EXISTS identity_orgs_email_idx ON identity_orgs (email);
"""

_DOWN = """
DROP INDEX IF EXISTS identity_orgs_email_idx;
DROP TABLE IF EXISTS identity_orgs;
ALTER TABLE user_sessions DROP COLUMN IF EXISTS active_org_id;
"""


def upgrade() -> None:
    op.execute(_DDL)


def downgrade() -> None:
    op.execute(_DOWN)
