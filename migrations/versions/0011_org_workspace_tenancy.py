"""org -> workspace tenancy ([2026] VJS-COUNTY 8, D1/D2/D3).

An ordered delta bringing an existing database up to carry the org/workspace
tenancy foundation. A fresh database already gets these tables from the baseline
replay of store/schema.sql; this migration is the in-place upgrade for a
provisioned one. Idempotent (CREATE TABLE / INDEX IF NOT EXISTS), matching
schema.sql exactly.

ADDITIVE only: this adds the org/workspace entities and membership ON TOP of the
existing tenant_id isolation key. It does NOT change the meaning of tenant_id and
does NOT add a workspace_id to any existing resource table (a later phase).

Adds:
  - organisations: the tenant boundary (D1). id IS the tenant_id (one org per
    tenant_id), so RLS stays keyed on tenant_id. slug is a unique url-safe handle;
    allow_own_ai_keys / require_two_factor are org-wide policy flags for later
    phases.
  - workspaces: a workspace belonging to an org (D2). Tenant-scoped.
  - org_members: organisation membership (D3). PK (tenant_id, user_id).
  - workspace_members: per-workspace membership (D3). PK (workspace_id, user_id),
    tenant-scoped by tenant_id.

Row-level tenant isolation for the four new tables is applied by the shared rls.sql
replay (which now lists workspaces/org_members/workspace_members generically and
organisations via its id-keyed policy) - not inline in the migration.

Revision ID: 0011_org_workspace_tenancy
Revises: 0010_first_party_login
"""

from __future__ import annotations

from alembic import op

revision = "0011_org_workspace_tenancy"
down_revision = "0010_first_party_login"
branch_labels = None
depends_on = None

_DDL = """
CREATE TABLE IF NOT EXISTS organisations (
    id                 TEXT NOT NULL,
    name               TEXT NOT NULL,
    slug               TEXT NOT NULL,
    settings           JSONB NOT NULL DEFAULT '{}'::jsonb,
    allow_own_ai_keys  BOOLEAN NOT NULL DEFAULT false,
    require_two_factor  BOOLEAN NOT NULL DEFAULT false,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE UNIQUE INDEX IF NOT EXISTS organisations_slug_idx ON organisations (slug);

CREATE TABLE IF NOT EXISTS workspaces (
    id          TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL,
    settings    JSONB NOT NULL DEFAULT '{}'::jsonb,
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE UNIQUE INDEX IF NOT EXISTS workspaces_slug_idx ON workspaces (slug);

CREATE TABLE IF NOT EXISTS org_members (
    tenant_id   TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'member',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, user_id)
);

CREATE TABLE IF NOT EXISTS workspace_members (
    workspace_id  TEXT NOT NULL,
    user_id       TEXT NOT NULL,
    tenant_id     TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'member',
    permissions   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, user_id)
);
CREATE INDEX IF NOT EXISTS workspace_members_user_idx
    ON workspace_members (tenant_id, user_id);
CREATE INDEX IF NOT EXISTS workspace_members_ws_idx
    ON workspace_members (tenant_id, workspace_id);
"""

_DOWN = """
DROP TABLE IF EXISTS workspace_members;
DROP TABLE IF EXISTS org_members;
DROP TABLE IF EXISTS workspaces;
DROP TABLE IF EXISTS organisations;
"""


def upgrade() -> None:
    op.execute(_DDL)


def downgrade() -> None:
    op.execute(_DOWN)
