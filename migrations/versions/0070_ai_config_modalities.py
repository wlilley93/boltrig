"""Add an optional vision AI-key route alongside the main text route."""

from __future__ import annotations

from alembic import op

revision = "0070_ai_config_modalities"
down_revision = "0069_agent_model_modalities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ai_configs ADD COLUMN IF NOT EXISTS modality "
        "TEXT NOT NULL DEFAULT 'text'"
    )
    op.execute("ALTER TABLE ai_configs DROP CONSTRAINT IF EXISTS ai_configs_pkey")
    op.execute(
        "ALTER TABLE ai_configs ADD PRIMARY KEY "
        "(tenant_id, level, scope_id, modality)"
    )
    op.execute(
        "ALTER TABLE ai_key_secret_proposals ADD COLUMN IF NOT EXISTS modality "
        "TEXT NOT NULL DEFAULT 'text'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE ai_key_secret_proposals DROP COLUMN IF EXISTS modality"
    )
    op.execute("ALTER TABLE ai_configs DROP CONSTRAINT IF EXISTS ai_configs_pkey")
    op.execute(
        "ALTER TABLE ai_configs ADD PRIMARY KEY (tenant_id, level, scope_id)"
    )
    op.execute("ALTER TABLE ai_configs DROP COLUMN IF EXISTS modality")
