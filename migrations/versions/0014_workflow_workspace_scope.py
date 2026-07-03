"""workspace-scope the workflow resources ([2026] VJS-COUNTY 8, D2).

An ordered delta bringing an existing database up to carry the per-workspace scope
on workflow definitions. A fresh database already gets the column from the baseline
replay of store/schema.sql; this migration is the in-place upgrade for a provisioned
one. Idempotent (ADD COLUMN IF NOT EXISTS / INDEX IF NOT EXISTS), matching schema.sql
exactly.

ADDITIVE + backward-compatible: the new workflow_definitions.workspace_id column is
NULLABLE and every existing row is left NULL. A NULL workspace_id means ORG-WIDE -
the workflow stays visible + runnable in every workspace of the org, exactly as
today - so an existing single-tenant deploy (all workflows NULL, no active
workspace) behaves EXACTLY as before. A SET value scopes the workflow to that one
workspace; the visibility + matching filter is an APPLICATION filter in
WorkflowLibrary, not RLS: RLS stays tenant_id-fenced (a workspace_id predicate would
hide the org-wide NULL rows, which every workspace must still see).

workflow_promotions does NOT follow: a promotion is keyed (tenant_id, workflow_id)
and is RANKING-ONLY (COUNTY 5); it maps to exactly one workflow whose row already
carries the workspace, and the matcher filters candidates by workspace BEFORE the
reuse weight is applied, so a promotion never needs its own workspace_id.

Revision ID: 0014_workflow_workspace_scope
Revises: 0013_ai_configs
"""

from __future__ import annotations

from alembic import op

revision = "0014_workflow_workspace_scope"
down_revision = "0013_ai_configs"
branch_labels = None
depends_on = None

_DDL = """
ALTER TABLE workflow_definitions ADD COLUMN IF NOT EXISTS workspace_id TEXT;
CREATE INDEX IF NOT EXISTS workflow_definitions_ws_idx
    ON workflow_definitions (tenant_id, workspace_id);
"""

_DOWN = """
DROP INDEX IF EXISTS workflow_definitions_ws_idx;
ALTER TABLE workflow_definitions DROP COLUMN IF EXISTS workspace_id;
"""


def upgrade() -> None:
    op.execute(_DDL)


def downgrade() -> None:
    op.execute(_DOWN)
