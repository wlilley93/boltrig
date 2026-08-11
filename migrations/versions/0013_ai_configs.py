"""per-org / workspace / user AI keys ([2026] VJS-COUNTY 8, D5).

An ordered delta bringing an existing database up to carry the AI-key config table.
A fresh database already gets this table from the baseline replay of
store/schema.sql; this migration is the in-place upgrade for a provisioned one.
Idempotent (CREATE TABLE IF NOT EXISTS), matching schema.sql exactly.

ADDITIVE + safe: an existing single-tenant deploy has NO ai_configs rows, so AI-key
resolution falls straight through to the manifest/env-configured provider key
exactly as before. The row carries a provider/model selection and a credential_ref
- the id of a SEALED credential in credential_refs - NEVER the raw key (there is no
plaintext key column).

Row-level tenant isolation for ai_configs is applied by the shared rls.sql replay
(which now lists ai_configs in the generic tenant_id-scoped set) - not inline here.

Revision ID: 0013_ai_configs
Revises: 0012_session_active_workspace
"""

from __future__ import annotations

from alembic import op

revision = "0013_ai_configs"
down_revision = "0012_session_active_workspace"
branch_labels = None
depends_on = None

_DDL = """
CREATE TABLE IF NOT EXISTS ai_configs (
    tenant_id      TEXT NOT NULL,
    level          TEXT NOT NULL,
    scope_id       TEXT NOT NULL,
    provider       TEXT NOT NULL,
    model          TEXT NOT NULL,
    credential_ref TEXT NOT NULL,
    modality       TEXT NOT NULL DEFAULT 'text',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, level, scope_id, modality)
);
"""

_DOWN = """
DROP TABLE IF EXISTS ai_configs;
"""


def upgrade() -> None:
    op.execute(_DDL)


def downgrade() -> None:
    op.execute(_DOWN)
