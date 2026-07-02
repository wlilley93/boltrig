"""chat attachments + append-plus-supersede marker (two court-bound features).

An ordered delta that brings an existing database up to carry inline chat
attachments ([2026] VJS-COUNTY 3) and the regenerate supersede marker ([2026]
VJS-COUNTY 4). A fresh database already gets both from the baseline replay of
store/schema.sql. Idempotent (ADD COLUMN IF NOT EXISTS), matching schema.sql.

- attachments:   inline, size-capped attachment records on the message row (an
                 inline JSONB blob, NOT an object store; see the decision doc).
- superseded_by: the id of the message that supersedes this one; a regenerate
                 appends a fresh reply and sets this marker on the old one.

Revision ID: 0006_chat_attachments_supersede
Revises: 0005_durable_delegation
"""

from __future__ import annotations

from alembic import op

revision = "0006_chat_attachments_supersede"
down_revision = "0005_durable_delegation"
branch_labels = None
depends_on = None

_DDL = """
ALTER TABLE conversation_messages ADD COLUMN IF NOT EXISTS attachments JSONB;
ALTER TABLE conversation_messages ADD COLUMN IF NOT EXISTS superseded_by TEXT;
"""


def upgrade() -> None:
    op.execute(_DDL)


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE conversation_messages DROP COLUMN IF EXISTS superseded_by;
        ALTER TABLE conversation_messages DROP COLUMN IF EXISTS attachments;
        """
    )
