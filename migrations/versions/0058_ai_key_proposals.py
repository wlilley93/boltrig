"""Short-lived envelope-sealed AI-key approval proposals.

Revision ID: 0058_ai_key_proposals
Revises: 0057_workflow_occurrence_lifecycle
"""

from __future__ import annotations

from alembic import op

revision = "0058_ai_key_proposals"
down_revision = "0057_workflow_occurrence_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_key_secret_proposals (
            id                     TEXT NOT NULL
                                   CHECK (id ~ '^akp_[a-f0-9]{32}$'),
            tenant_id              TEXT NOT NULL,
            requested_by           TEXT NOT NULL,
            requested_on_behalf_of TEXT,
            workspace_id           TEXT,
            level                  TEXT NOT NULL
                                   CHECK (level IN ('org','workspace','user')),
            scope_id               TEXT NOT NULL,
            provider               TEXT NOT NULL,
            model                  TEXT NOT NULL,
            base_url               TEXT,
            secret_ref             TEXT,
            secret_digest          TEXT NOT NULL
                                   CHECK (secret_digest ~ '^[a-f0-9]{64}$'),
            status                 TEXT NOT NULL DEFAULT 'pending'
                                   CHECK (status IN (
                                     'pending','consumed','rejected','expired',
                                     'invalidated'
                                   )),
            approval_id            TEXT,
            created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at             TIMESTAMPTZ NOT NULL,
            updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
            consumed_at            TIMESTAMPTZ,
            PRIMARY KEY (tenant_id,id),
            FOREIGN KEY (tenant_id,approval_id)
              REFERENCES hitl_requests(tenant_id,id),
            CONSTRAINT ai_key_secret_proposal_bounded_expiry CHECK (
              expires_at > created_at
              AND expires_at <= created_at + interval '15 minutes'
            ),
            CONSTRAINT ai_key_secret_proposal_state_shape CHECK (
              (status='pending'
               AND secret_ref IS NOT NULL
               AND consumed_at IS NULL)
              OR
              (status='consumed'
               AND secret_ref IS NULL
               AND consumed_at IS NOT NULL)
              OR
              (status IN ('rejected','expired','invalidated')
               AND secret_ref IS NULL
               AND consumed_at IS NULL)
            )
        );
        CREATE INDEX IF NOT EXISTS ai_key_secret_proposals_requester_idx
          ON ai_key_secret_proposals (
            tenant_id,requested_by,requested_on_behalf_of,created_at DESC
          );

        ALTER TABLE ai_key_secret_proposals ENABLE ROW LEVEL SECURITY;
        ALTER TABLE ai_key_secret_proposals FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON ai_key_secret_proposals;
        CREATE POLICY tenant_isolation ON ai_key_secret_proposals
          USING (tenant_id = current_setting('app.tenant_id', true))
          WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ai_key_secret_proposals;")
