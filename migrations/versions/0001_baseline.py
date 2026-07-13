"""baseline: the immutable Round Three Boltrig schema (FR-OPS-01).

This revision applies the schema as it existed when the migration chain began.
Later revisions own every subsequent change. Keeping the baseline immutable is
what makes an Alembic replay meaningful; a parity test compares the resulting
head with the convenience bootstrap schema.

Revision ID: 0001_baseline
Revises:
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None

# Frozen at revision creation. Never point this back at the mutable bootstrap
# schema: doing so makes old revisions silently change under deployed databases.
_SCHEMA = Path(__file__).resolve().parents[1] / "baseline.sql"


def upgrade() -> None:
    op.execute(_SCHEMA.read_text())


def downgrade() -> None:
    # The baseline is the floor; there is nothing below it to migrate down to.
    raise NotImplementedError("0001_baseline is the schema floor; no downgrade")
