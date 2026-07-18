"""Introduce the digest-only model-proxy grant schema.

Revision ID: 0029_model_proxy_grants
Revises: 0028_grant_leases
"""

from __future__ import annotations

from alembic import op

revision = "0029_model_proxy_grants"
down_revision = "0028_grant_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS model_proxy_grants (
            grant_id                     TEXT NOT NULL,
            tenant_id                    TEXT NOT NULL,
            workspace_id                 TEXT NOT NULL,
            root_run_id                  TEXT NOT NULL,
            phase_id                     TEXT NOT NULL,
            assignment_id                TEXT NOT NULL,
            cell_id                      TEXT NOT NULL,
            pid                          BIGINT NOT NULL,
            pid_start_ticks              BIGINT NOT NULL,
            boot_id                      TEXT NOT NULL,
            pid_namespace_inode          BIGINT NOT NULL,
            cgroup_identity_digest       TEXT NOT NULL,
            model_id                     TEXT NOT NULL,
            model_policy_digest          TEXT NOT NULL,
            budget_id                    TEXT NOT NULL,
            max_input_tokens             BIGINT NOT NULL,
            max_output_tokens            BIGINT NOT NULL,
            max_total_tokens             BIGINT NOT NULL,
            max_cost_micros              BIGINT NOT NULL,
            budget_policy_digest         TEXT NOT NULL,
            bearer_digest                TEXT NOT NULL,
            startup_request_digest       TEXT NOT NULL,
            issued_at                    TIMESTAMPTZ NOT NULL,
            expires_at                   TIMESTAMPTZ NOT NULL,
            generation                   BIGINT NOT NULL,
            status                       TEXT NOT NULL,
            revoked_at                   TIMESTAMPTZ,
            revocation_reason            TEXT,
            created_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
            engine_owner                 TEXT NOT NULL DEFAULT 'boltrig',
            PRIMARY KEY (grant_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS model_proxy_grant_cancelled_roots (
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
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS model_proxy_grant_cancelled_phases (
            tenant_id       TEXT NOT NULL,
            workspace_id    TEXT NOT NULL,
            root_run_id     TEXT NOT NULL,
            phase_id        TEXT NOT NULL,
            cancelled_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            reason          TEXT NOT NULL,
            engine_owner    TEXT NOT NULL DEFAULT 'boltrig',
            PRIMARY KEY (tenant_id, workspace_id, root_run_id, phase_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS model_proxy_grant_cancelled_assignments (
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
        CREATE TABLE IF NOT EXISTS model_proxy_grant_cancelled_cells (
            tenant_id                TEXT NOT NULL,
            workspace_id             TEXT NOT NULL,
            root_run_id              TEXT NOT NULL,
            phase_id                 TEXT NOT NULL,
            assignment_id            TEXT NOT NULL,
            cell_id                  TEXT NOT NULL,
            pid                      BIGINT NOT NULL,
            pid_start_ticks          BIGINT NOT NULL,
            boot_id                  TEXT NOT NULL,
            pid_namespace_inode      BIGINT NOT NULL,
            cgroup_identity_digest   TEXT NOT NULL,
            cancelled_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
            reason                   TEXT NOT NULL,
            engine_owner             TEXT NOT NULL DEFAULT 'boltrig',
            PRIMARY KEY (
                tenant_id, workspace_id, root_run_id, phase_id, assignment_id,
                cell_id, pid, pid_start_ticks, boot_id, pid_namespace_inode,
                cgroup_identity_digest
            )
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS model_proxy_grant_cancelled_cells")
    op.execute("DROP TABLE IF EXISTS model_proxy_grant_cancelled_assignments")
    op.execute("DROP TABLE IF EXISTS model_proxy_grant_cancelled_phases")
    op.execute("DROP TABLE IF EXISTS model_proxy_grant_cancelled_roots")
    op.execute("DROP TABLE IF EXISTS model_proxy_grants")
