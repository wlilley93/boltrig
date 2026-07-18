"""Introduce the canonical execution-ledger schema.

Revision ID: 0026_execution_ledger
Revises: 0025_hitl_access_scope
"""

from __future__ import annotations

from alembic import op

revision = "0026_execution_ledger"
down_revision = "0025_hitl_access_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS execution_root_runs (
            tenant_id               TEXT NOT NULL,
            workspace_id            TEXT NOT NULL,
            root_run_id             TEXT NOT NULL,
            requested_by_user_id    TEXT NOT NULL,
            objective_digest        TEXT NOT NULL,
            profile                 JSONB NOT NULL,
            policy_generation       INT NOT NULL,
            status                  TEXT NOT NULL,
            cancellation            JSONB,
            final_synthesis_digest  TEXT,
            version                 INT NOT NULL,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            engine_owner            TEXT NOT NULL DEFAULT 'boltrig',
            PRIMARY KEY (tenant_id, workspace_id, root_run_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS execution_phases (
            tenant_id           TEXT NOT NULL,
            workspace_id        TEXT NOT NULL,
            root_run_id         TEXT NOT NULL,
            id                  TEXT NOT NULL,
            ordinal             INT NOT NULL,
            name                TEXT NOT NULL,
            objective_digest    TEXT NOT NULL,
            mode                TEXT NOT NULL,
            profile             JSONB NOT NULL,
            skills              JSONB NOT NULL,
            policy_generation   INT NOT NULL,
            dependencies        JSONB NOT NULL,
            retry               JSONB NOT NULL,
            status              TEXT NOT NULL,
            terminal_outcome    JSONB,
            version             INT NOT NULL,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            engine_owner        TEXT NOT NULL DEFAULT 'boltrig',
            PRIMARY KEY (tenant_id, workspace_id, root_run_id, id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS execution_work_items (
            tenant_id               TEXT NOT NULL,
            workspace_id            TEXT NOT NULL,
            root_run_id             TEXT NOT NULL,
            id                      TEXT NOT NULL,
            phase_id                TEXT NOT NULL,
            ordinal                 INT NOT NULL,
            intent_digest           TEXT NOT NULL,
            dependencies            JSONB NOT NULL,
            parent_id               TEXT,
            requires_verification   BOOLEAN NOT NULL,
            status                  TEXT NOT NULL,
            version                 INT NOT NULL,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            engine_owner            TEXT NOT NULL DEFAULT 'boltrig',
            PRIMARY KEY (tenant_id, workspace_id, root_run_id, id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS execution_assignments (
            tenant_id               TEXT NOT NULL,
            workspace_id            TEXT NOT NULL,
            root_run_id             TEXT NOT NULL,
            id                      TEXT NOT NULL,
            phase_id                TEXT NOT NULL,
            work_item_id            TEXT NOT NULL,
            runtime_identity_id     TEXT NOT NULL,
            attempt                 INT NOT NULL,
            profile                 JSONB NOT NULL,
            skills                  JSONB NOT NULL,
            authority               JSONB NOT NULL,
            lease                   JSONB,
            replaces_assignment_id  TEXT,
            status                  TEXT NOT NULL,
            version                 INT NOT NULL,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            engine_owner            TEXT NOT NULL DEFAULT 'boltrig',
            PRIMARY KEY (tenant_id, workspace_id, root_run_id, id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS execution_results (
            tenant_id           TEXT NOT NULL,
            workspace_id        TEXT NOT NULL,
            root_run_id         TEXT NOT NULL,
            id                  TEXT NOT NULL,
            phase_id            TEXT NOT NULL,
            work_item_id        TEXT NOT NULL,
            assignment_id       TEXT NOT NULL,
            output_digest       TEXT NOT NULL,
            status              TEXT NOT NULL,
            evidence            JSONB NOT NULL,
            findings            JSONB NOT NULL,
            blockers            JSONB NOT NULL,
            handoffs            JSONB NOT NULL,
            usage               JSONB NOT NULL,
            completed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            engine_owner        TEXT NOT NULL DEFAULT 'boltrig',
            PRIMARY KEY (tenant_id, workspace_id, root_run_id, id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS execution_verifications (
            tenant_id           TEXT NOT NULL,
            workspace_id        TEXT NOT NULL,
            root_run_id         TEXT NOT NULL,
            id                  TEXT NOT NULL,
            phase_id            TEXT NOT NULL,
            work_item_id        TEXT NOT NULL,
            result_id           TEXT NOT NULL,
            status              TEXT NOT NULL,
            evidence_digest     TEXT NOT NULL,
            checks              JSONB NOT NULL,
            verified_by         JSONB,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            engine_owner        TEXT NOT NULL DEFAULT 'boltrig',
            PRIMARY KEY (tenant_id, workspace_id, root_run_id, id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS execution_commands (
            tenant_id           TEXT NOT NULL,
            workspace_id        TEXT NOT NULL,
            root_run_id         TEXT NOT NULL,
            command_id          TEXT NOT NULL,
            request_digest      TEXT NOT NULL,
            aggregate_kind      TEXT NOT NULL,
            aggregate_id        TEXT NOT NULL,
            status              TEXT NOT NULL,
            previous_version    INT,
            resulting_version   INT,
            submitted           JSONB NOT NULL,
            recorded_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, workspace_id, root_run_id, command_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS execution_events (
            tenant_id           TEXT NOT NULL,
            workspace_id        TEXT NOT NULL,
            root_run_id         TEXT NOT NULL,
            sequence            BIGINT NOT NULL,
            event_id            TEXT NOT NULL,
            aggregate_kind      TEXT NOT NULL,
            aggregate_id        TEXT NOT NULL,
            kind                TEXT NOT NULL,
            idempotency_key     TEXT NOT NULL,
            correlation_id      TEXT NOT NULL,
            causation_command_id TEXT,
            source_owner        TEXT NOT NULL,
            source_sequence     BIGINT,
            payload             JSONB NOT NULL,
            occurred_at         TIMESTAMPTZ NOT NULL,
            recorded_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            engine_owner        TEXT NOT NULL DEFAULT 'boltrig',
            PRIMARY KEY (tenant_id, workspace_id, root_run_id, sequence)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS execution_outbox (
            tenant_id           TEXT NOT NULL,
            workspace_id        TEXT NOT NULL,
            root_run_id         TEXT NOT NULL,
            id                  TEXT NOT NULL,
            event_sequence      BIGINT NOT NULL,
            destination         TEXT NOT NULL,
            delivery_key        TEXT NOT NULL,
            status              TEXT NOT NULL,
            attempts            INT NOT NULL DEFAULT 0,
            claim_owner         TEXT,
            claimed_at          TIMESTAMPTZ,
            claim_expires_at    TIMESTAMPTZ,
            available_at        TIMESTAMPTZ NOT NULL,
            delivered_at        TIMESTAMPTZ,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            engine_owner        TEXT NOT NULL DEFAULT 'boltrig',
            PRIMARY KEY (tenant_id, workspace_id, root_run_id, id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_identities (
            tenant_id           TEXT NOT NULL,
            workspace_id        TEXT NOT NULL,
            id                  TEXT NOT NULL,
            status              TEXT NOT NULL,
            generation          INT NOT NULL,
            profile             JSONB,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, workspace_id, id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS codex_thread_bindings (
            tenant_id                   TEXT NOT NULL,
            workspace_id                TEXT NOT NULL,
            root_run_id                 TEXT NOT NULL,
            phase_id                    TEXT NOT NULL,
            assignment_id               TEXT NOT NULL,
            runtime_identity_id         TEXT NOT NULL,
            kind                        TEXT NOT NULL,
            thread_id                   TEXT NOT NULL,
            native_parent_thread_id     TEXT,
            bound_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
            engine_owner                TEXT NOT NULL DEFAULT 'boltrig',
            runtime_source_owner        TEXT NOT NULL DEFAULT 'codex',
            PRIMARY KEY (tenant_id, workspace_id, root_run_id, thread_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS codex_turn_bindings (
            tenant_id                   TEXT NOT NULL,
            workspace_id                TEXT NOT NULL,
            root_run_id                 TEXT NOT NULL,
            thread_id                   TEXT NOT NULL,
            kind                        TEXT NOT NULL,
            turn_id                     TEXT NOT NULL,
            native_parent_turn_id       TEXT,
            bound_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
            engine_owner                TEXT NOT NULL DEFAULT 'boltrig',
            runtime_source_owner        TEXT NOT NULL DEFAULT 'codex',
            PRIMARY KEY (tenant_id, workspace_id, root_run_id, thread_id, turn_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS codex_item_bindings (
            tenant_id                   TEXT NOT NULL,
            workspace_id                TEXT NOT NULL,
            root_run_id                 TEXT NOT NULL,
            thread_id                   TEXT NOT NULL,
            turn_id                     TEXT NOT NULL,
            kind                        TEXT NOT NULL,
            item_id                     TEXT NOT NULL,
            native_parent_item_id       TEXT,
            bound_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
            engine_owner                TEXT NOT NULL DEFAULT 'boltrig',
            runtime_source_owner        TEXT NOT NULL DEFAULT 'codex',
            PRIMARY KEY (tenant_id, workspace_id, root_run_id, thread_id, turn_id, item_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS codex_item_bindings")
    op.execute("DROP TABLE IF EXISTS codex_turn_bindings")
    op.execute("DROP TABLE IF EXISTS codex_thread_bindings")
    op.execute("DROP TABLE IF EXISTS runtime_identities")
    op.execute("DROP TABLE IF EXISTS execution_outbox")
    op.execute("DROP TABLE IF EXISTS execution_events")
    op.execute("DROP TABLE IF EXISTS execution_commands")
    op.execute("DROP TABLE IF EXISTS execution_verifications")
    op.execute("DROP TABLE IF EXISTS execution_results")
    op.execute("DROP TABLE IF EXISTS execution_assignments")
    op.execute("DROP TABLE IF EXISTS execution_work_items")
    op.execute("DROP TABLE IF EXISTS execution_phases")
    op.execute("DROP TABLE IF EXISTS execution_root_runs")
