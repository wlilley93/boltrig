"""Redacted cross-process birth-profile startup receipts.

Revision ID: 0056_birth_profile_receipts
Revises: 0055_workflow_schedules
"""

from __future__ import annotations

from alembic import op

revision = "0056_birth_profile_receipts"
down_revision = "0055_workflow_schedules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS birth_profile_receipts (
            tenant_id                TEXT NOT NULL,
            process_kind             TEXT NOT NULL
                                     CHECK (process_kind IN ('api','fleet','hatchet')),
            instance_identity        TEXT NOT NULL
                                     CHECK (instance_identity ~ '^bi_[a-f0-9]{24}$'),
            manifest_generation      TEXT NOT NULL
                                     CHECK (manifest_generation ~ '^mf_[a-f0-9]{24}$'),
            addon_set_identity       TEXT NOT NULL
                                     CHECK (addon_set_identity ~ '^as_[a-f0-9]{24}$'),
            codex_provider_identity  TEXT NOT NULL
                                     CHECK (
                                       codex_provider_identity = 'cp_off_v1'
                                       OR codex_provider_identity ~ '^cp_[a-f0-9]{24}$'
                                     ),
            codex_provider_state     TEXT NOT NULL
                                     CHECK (codex_provider_state IN ('off','configured')),
            sensitive_role_identity  TEXT NOT NULL
                                     CHECK (
                                       sensitive_role_identity = 'sr_absent_v1'
                                       OR sensitive_role_identity ~ '^sr_[a-f0-9]{24}$'
                                     ),
            sensitive_role_state     TEXT NOT NULL
                                     CHECK (sensitive_role_state IN ('absent','configured')),
            receipt_kind             TEXT NOT NULL DEFAULT 'startup_snapshot'
                                     CHECK (receipt_kind = 'startup_snapshot'),
            observed_at              TIMESTAMPTZ NOT NULL,
            expires_at               TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (tenant_id, process_kind, instance_identity),
            CONSTRAINT birth_profile_codex_shape CHECK (
              (codex_provider_state = 'off'
                AND codex_provider_identity = 'cp_off_v1')
              OR
              (codex_provider_state = 'configured'
                AND codex_provider_identity ~ '^cp_[a-f0-9]{24}$')
            ),
            CONSTRAINT birth_profile_sensitive_shape CHECK (
              (sensitive_role_state = 'absent'
                AND sensitive_role_identity = 'sr_absent_v1')
              OR
              (sensitive_role_state = 'configured'
                AND sensitive_role_identity ~ '^sr_[a-f0-9]{24}$')
            ),
            CONSTRAINT birth_profile_expiry_bounded CHECK (
              expires_at > observed_at
              AND expires_at <= observed_at + interval '1 hour'
            )
        );
        CREATE INDEX IF NOT EXISTS birth_profile_receipts_observed_idx
          ON birth_profile_receipts (tenant_id, observed_at DESC);

        ALTER TABLE birth_profile_receipts ENABLE ROW LEVEL SECURITY;
        ALTER TABLE birth_profile_receipts FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON birth_profile_receipts;
        CREATE POLICY tenant_isolation ON birth_profile_receipts
          USING (tenant_id = current_setting('app.tenant_id', true))
          WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS birth_profile_receipts;")
