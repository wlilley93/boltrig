"""Add a generic per-agent model-route projection.

The legacy text and vision columns remain for compatibility with older
manifests and runtime readers. New modality overrides (STT, TTS and realtime
voice) are stored in one governed JSON object so each new modality does not
require another schema column.
"""

from __future__ import annotations

from alembic import op

revision = "0073_agent_model_routes"
down_revision = "0072_device_workspace_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE agent_capabilities ADD COLUMN IF NOT EXISTS "
        "model_routes JSONB NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute(
        "UPDATE agent_capabilities SET model_routes = "
        "jsonb_strip_nulls(jsonb_build_object('text', model_endpoint, "
        "'vision', vision_model_endpoint)) || model_routes "
        "WHERE model_routes = '{}'::jsonb"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE agent_capabilities DROP COLUMN IF EXISTS model_routes"
    )
