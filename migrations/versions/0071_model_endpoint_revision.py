"""Monotonic model-endpoint generations for approved compare-and-swap edits."""

from __future__ import annotations

from alembic import op

revision = "0071_model_endpoint_revision"
down_revision = "0070_ai_config_modalities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE model_endpoints ADD COLUMN IF NOT EXISTS "
        "revision BIGINT NOT NULL DEFAULT 1"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE model_endpoints DROP COLUMN IF EXISTS revision")
