"""baseline: the full Boltrig schema (FR-OPS-01).

This revision applies store/schema.sql verbatim so the Alembic head equals the
hand-maintained schema. ``alembic upgrade head`` on a fresh database produces
exactly the bootstrap schema (kernel core + Round Two + Round Three tables).

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

# store/schema.sql is the source of truth (P1); the baseline replays it.
_SCHEMA = Path(__file__).resolve().parents[2] / "boltrig" / "store" / "schema.sql"


def upgrade() -> None:
    op.execute(_SCHEMA.read_text())


def downgrade() -> None:
    # The baseline is the floor; there is nothing below it to migrate down to.
    raise NotImplementedError("0001_baseline is the schema floor; no downgrade")
