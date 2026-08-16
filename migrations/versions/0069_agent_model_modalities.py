"""Per-agent vision routing and explicit model modalities."""

from __future__ import annotations

from alembic import op

revision = "0069_agent_model_modalities"
down_revision = "0068_camera_uvc_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE agent_capabilities ADD COLUMN IF NOT EXISTS "
        "vision_model_endpoint TEXT"
    )
    op.execute(
        "ALTER TABLE model_endpoints ADD COLUMN IF NOT EXISTS modalities "
        "JSONB NOT NULL DEFAULT '[\"text\"]'::jsonb"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE agent_capabilities DROP COLUMN IF EXISTS vision_model_endpoint"
    )
    op.execute(
        "ALTER TABLE model_endpoints DROP COLUMN IF EXISTS modalities"
    )
