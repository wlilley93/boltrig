"""Introduce the run-scoped grant-lease schema.

Revision ID: 0028_grant_leases
Revises: 0027_root_engine_decisions
"""

from __future__ import annotations

from alembic import op

revision = "0028_grant_leases"
down_revision = "0027_root_engine_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS grant_leases (
            lease_id                          TEXT NOT NULL,
            tenant_id                         TEXT NOT NULL,
            workspace_id                      TEXT NOT NULL,
            root_run_id                       TEXT NOT NULL,
            phase_id                          TEXT NOT NULL,
            assignment_id                     TEXT NOT NULL,
            issue_operation_id                TEXT NOT NULL,
            token_digest                      TEXT NOT NULL,
            authority_evaluation_id           TEXT NOT NULL,
            authority_evaluation_digest       TEXT NOT NULL,
            authority_policy_generation       BIGINT NOT NULL,
            permitted_verbs                   JSONB NOT NULL,
            issued_at                         TIMESTAMPTZ NOT NULL,
            expires_at                        TIMESTAMPTZ NOT NULL,
            max_ttl_seconds                   INT NOT NULL,
            expected_current_lease_generation BIGINT,
            lease_generation                  BIGINT NOT NULL,
            status                            TEXT NOT NULL,
            revoked_at                        TIMESTAMPTZ,
            revocation_reason                 TEXT,
            created_at                        TIMESTAMPTZ NOT NULL DEFAULT now(),
            engine_owner                      TEXT NOT NULL DEFAULT 'boltrig',
            PRIMARY KEY (lease_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS grant_authority_snapshots (
            tenant_id                     TEXT NOT NULL,
            workspace_id                  TEXT NOT NULL,
            root_run_id                   TEXT NOT NULL,
            phase_id                      TEXT NOT NULL,
            assignment_id                 TEXT NOT NULL,
            authority_evaluation_id       TEXT NOT NULL,
            authority_evaluation_digest   TEXT NOT NULL,
            authority_policy_generation   BIGINT NOT NULL,
            permitted_verbs               JSONB NOT NULL,
            installed_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
            engine_owner                  TEXT NOT NULL DEFAULT 'boltrig',
            PRIMARY KEY (tenant_id, workspace_id, root_run_id, phase_id, assignment_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS grant_lease_cancelled_assignments (
            tenant_id       TEXT NOT NULL,
            workspace_id    TEXT NOT NULL,
            root_run_id     TEXT NOT NULL,
            phase_id        TEXT NOT NULL,
            assignment_id   TEXT NOT NULL,
            cancelled_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            reason          TEXT NOT NULL,
            engine_owner    TEXT NOT NULL DEFAULT 'boltrig',
            PRIMARY KEY (tenant_id, workspace_id, root_run_id, phase_id, assignment_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS grant_lease_cancelled_roots (
            tenant_id       TEXT NOT NULL,
            workspace_id    TEXT NOT NULL,
            root_run_id     TEXT NOT NULL,
            cancelled_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            reason          TEXT NOT NULL,
            engine_owner    TEXT NOT NULL DEFAULT 'boltrig',
            PRIMARY KEY (tenant_id, workspace_id, root_run_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS grant_lease_cancelled_roots")
    op.execute("DROP TABLE IF EXISTS grant_lease_cancelled_assignments")
    op.execute("DROP TABLE IF EXISTS grant_authority_snapshots")
    op.execute("DROP TABLE IF EXISTS grant_leases")
