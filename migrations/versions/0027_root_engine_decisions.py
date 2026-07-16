"""Introduce the immutable root-engine decision schema.

Revision ID: 0027_root_engine_decisions
Revises: 0026_execution_ledger
"""

from __future__ import annotations

from alembic import op

revision = "0027_root_engine_decisions"
down_revision = "0026_execution_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS root_engine_decisions (
            tenant_id               TEXT NOT NULL,
            workspace_id            TEXT NOT NULL,
            root_run_id             TEXT NOT NULL,
            workload                TEXT NOT NULL,
            compatibility           TEXT NOT NULL,
            policy_generation       INT NOT NULL,
            policy_digest           TEXT NOT NULL,
            route                   TEXT NOT NULL,
            execution_result_source TEXT NOT NULL,
            reason_code             TEXT NOT NULL,
            canary_bucket           INT,
            decision_digest         TEXT NOT NULL,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            engine_owner            TEXT NOT NULL DEFAULT 'boltrig',
            PRIMARY KEY (tenant_id, workspace_id, root_run_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS root_engine_decisions")
