"""ai_config model/provider routing: optional base_url ([2026] VJS-COUNTY 8, D5).

Adds the OPTIONAL ``base_url`` column to ``ai_configs`` so a config can name the
provider host its selected model/provider routes to (the model/provider-routing
seam). A fresh database already gets this column from the baseline replay of
store/schema.sql; this migration is the in-place upgrade for a provisioned one.
Idempotent (ADD COLUMN IF NOT EXISTS), matching schema.sql exactly.

ADDITIVE + safe: the column is nullable with no default, so every existing row reads
base_url = NULL and routing falls straight through to the endpoint's own base_url -
an existing deploy is byte-for-byte unchanged. It is routing metadata, NEVER a
secret (the sealed key still lives only in credential_refs).

Revision ID: 0017_ai_config_base_url
Revises: 0016_audit_opbox_depth
"""

from __future__ import annotations

from alembic import op

revision = "0017_ai_config_base_url"
down_revision = "0016_audit_opbox_depth"
branch_labels = None
depends_on = None

_UP = """
ALTER TABLE ai_configs ADD COLUMN IF NOT EXISTS base_url TEXT;
"""

_DOWN = """
ALTER TABLE ai_configs DROP COLUMN IF EXISTS base_url;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
