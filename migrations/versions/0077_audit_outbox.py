"""The durable audit outbox (SEC-16 audit-always).

Revision ID: 0077_audit_outbox
Revises: 0076_typed_memory_ledger
"""

from __future__ import annotations

from alembic import op

revision = "0077_audit_outbox"
down_revision = "0076_typed_memory_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_outbox (
            id             BIGSERIAL PRIMARY KEY,
            tenant_id      TEXT NOT NULL,
            payload        JSONB NOT NULL,
            append_error   TEXT,
            attempts       INT NOT NULL DEFAULT 0,
            next_retry_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS audit_outbox_due_idx
          ON audit_outbox (next_retry_at);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS audit_outbox_due_idx;
        DROP TABLE IF EXISTS audit_outbox;
        """
    )
