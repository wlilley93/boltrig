"""extension contract: the skill shelf label (skills.description).

An ordered delta that adds the skill registry's shelf label to an existing
database; a fresh database already gets it from the baseline replay of
store/schema.sql. Idempotent (ADD COLUMN IF NOT EXISTS), matching schema.sql.

Revision ID: 0004_extension_contract
Revises: 0003_round_five
"""

from __future__ import annotations

from alembic import op

revision = "0004_extension_contract"
down_revision = "0003_round_five"
branch_labels = None
depends_on = None

_DDL = """
ALTER TABLE skills ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT '';
"""


def upgrade() -> None:
    op.execute(_DDL)


def downgrade() -> None:
    op.execute("ALTER TABLE skills DROP COLUMN IF EXISTS description")
