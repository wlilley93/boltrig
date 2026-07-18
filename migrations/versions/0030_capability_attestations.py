"""Introduce the immutable, assignment-pinned capability attestation schema.

Revision ID: 0030_capability_attestations
Revises: 0029_model_proxy_grants
"""

from __future__ import annotations

from alembic import op

revision = "0030_capability_attestations"
down_revision = "0029_model_proxy_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS capability_attestation_sets (
            tenant_id                     TEXT NOT NULL,
            workspace_id                  TEXT NOT NULL,
            root_run_id                   TEXT NOT NULL,
            phase_id                      TEXT NOT NULL,
            assignment_id                 TEXT NOT NULL,
            authority_evaluation_id       TEXT NOT NULL,
            authority_evaluation_digest   TEXT NOT NULL,
            authority_policy_generation   BIGINT NOT NULL,
            catalog_generation            BIGINT NOT NULL,
            catalog_digest                TEXT NOT NULL,
            set_digest                    TEXT NOT NULL,
            created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
            engine_owner                  TEXT NOT NULL DEFAULT 'boltrig',
            PRIMARY KEY (tenant_id, workspace_id, root_run_id, phase_id, assignment_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS capability_attestation_entries (
            tenant_id           TEXT NOT NULL,
            workspace_id        TEXT NOT NULL,
            root_run_id         TEXT NOT NULL,
            phase_id            TEXT NOT NULL,
            assignment_id       TEXT NOT NULL,
            verb_id             TEXT NOT NULL,
            definition_digest   TEXT NOT NULL,
            effect_class        TEXT NOT NULL,
            consequence         TEXT NOT NULL,
            engine_owner        TEXT NOT NULL DEFAULT 'boltrig',
            PRIMARY KEY (
                tenant_id, workspace_id, root_run_id, phase_id, assignment_id, verb_id
            ),
            FOREIGN KEY (
                tenant_id, workspace_id, root_run_id, phase_id, assignment_id
            ) REFERENCES capability_attestation_sets (
                tenant_id, workspace_id, root_run_id, phase_id, assignment_id
            ) ON DELETE CASCADE
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS capability_attestation_entries")
    op.execute("DROP TABLE IF EXISTS capability_attestation_sets")
