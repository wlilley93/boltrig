"""workflow_promotions: drop a table nothing production ever read.

[2026] VJS-CC-BOLTRIG-WORKFLOW-PROMOTION-TRIGGER-001 D3. The promotion subsystem
stored a reuse-ranking state per workflow. Its only reader was
`WorkflowLibrary.match`, whose only caller is `select_or_generate_workflow`, which
no production entry point calls: production selects a workflow by explicit id
(`control.workflow.trigger`, `control.workflow.execute`, and the pump's addressed
`workflow:<id>` target), never by intent. So every row this table could hold was
written by a path only tests ran and read by a path only tests reached.

The court refused to choose a WRITE trigger for a value with no consumer and
ordered the consumer retired first. The write machinery (WorkflowPromoter,
reuse_weight, apply_promotion_signal), the WorkflowPromotion model, the three
store methods and the RLS grant go with it; this migration takes the table.

Not a data-loss hazard on any deployment: the table is empty everywhere, because
the only writer was constructed into `app.state.platform["promoter"]`, a key no
reader ever looked up. `0008_workflow_promotions` created it and is left exactly
as it is - editing an applied revision changes its checksum and blocks boot.

If reuse ranking is ever wanted again it is DERIVED from the eval cases and their
runs, pinned by the definition digest: no table, no writer, no trigger (that
order, forbidden clause 4).

Revision ID: 0040_drop_workflow_promotions
Revises: 0039_user_must_change_password
"""

from __future__ import annotations

from alembic import op

revision = "0040_drop_workflow_promotions"
down_revision = "0039_user_must_change_password"
branch_labels = None
depends_on = None

# Idempotent and schema-RELATIVE, matching the house style: a fresh database never
# gets the table at all (the schema.sql baseline no longer defines it), so this
# must be a clean no-op there, and the migration-parity harness applies this SQL
# inside a NAMED schema via search_path, where an unqualified name is correct and
# a hardcoded `public.` would resolve somewhere else.
_UP = """
DROP TABLE IF EXISTS workflow_promotions;
"""

# The down leg restores the table 0008 created, byte-for-byte in shape, so a
# downgrade past this revision leaves the catalogue as 0008 through 0039 left it.
# It cannot restore rows, which costs nothing: there were never any.
_DOWN = """
CREATE TABLE IF NOT EXISTS workflow_promotions (
    workflow_id TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    state       TEXT NOT NULL DEFAULT 'candidate',
    score       DOUBLE PRECISION NOT NULL DEFAULT 0,
    eval_run_id TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, workflow_id)
);
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
