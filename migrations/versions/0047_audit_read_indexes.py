"""Indexes for filter-before-page account activity reads.

Revision ID: 0047_audit_read_indexes
Revises: 0046_realtime_call_recovery
"""

from __future__ import annotations

from alembic import op

revision = "0047_audit_read_indexes"
down_revision = "0046_realtime_call_recovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS audit_actor_page_idx "
        "ON audit_log (tenant_id, actor, seq DESC);"
        "CREATE INDEX IF NOT EXISTS audit_behalf_page_idx "
        "ON audit_log (tenant_id, on_behalf_of, seq DESC);"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS audit_behalf_page_idx;"
        "DROP INDEX IF EXISTS audit_actor_page_idx;"
    )
