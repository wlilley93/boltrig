"""Immutable owner/workspace-scoped artifact storage.

Revision ID: 0044_artifacts
Revises: 0043_integration_connections
"""

from __future__ import annotations

from alembic import op

revision = "0044_artifacts"
down_revision = "0043_integration_connections"
branch_labels = None
depends_on = None

_UP = r"""
CREATE TABLE artifacts (
    id TEXT NOT NULL, tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL,
    workspace_id TEXT, conversation_id TEXT, run_id TEXT, work_item_id TEXT,
    name TEXT NOT NULL, digest TEXT NOT NULL, media_type TEXT NOT NULL,
    size BIGINT NOT NULL, revision INT NOT NULL,
    previous_revision_id TEXT, provenance JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), content BYTEA NOT NULL,
    PRIMARY KEY (tenant_id,id),
    UNIQUE (tenant_id,previous_revision_id),
    CONSTRAINT artifact_name_safe CHECK (
      octet_length(name) BETWEEN 1 AND 255
      AND name NOT IN ('.','..') AND name !~ '[\\/]'
      AND name !~ '[[:cntrl:]]'
    ),
    CONSTRAINT artifact_digest_sha256 CHECK (digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT artifact_media_type_valid CHECK (
      media_type ~ '^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+$'
    ),
    CONSTRAINT artifact_size_bounded CHECK (
      size BETWEEN 0 AND 104857600 AND octet_length(content)=size
    ),
    CONSTRAINT artifact_revision_valid CHECK (
      revision BETWEEN 1 AND 1000000
      AND ((revision=1) = (previous_revision_id IS NULL))
    ),
    CONSTRAINT artifact_provenance_valid CHECK (
      jsonb_typeof(provenance)='object'
      AND provenance->>'kind' IN ('agent','tool','workflow','call','system')
    ),
    FOREIGN KEY (tenant_id,workspace_id)
      REFERENCES workspaces(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,conversation_id)
      REFERENCES conversations(tenant_id,id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id,previous_revision_id)
      REFERENCES artifacts(tenant_id,id) ON DELETE RESTRICT
);
CREATE INDEX artifacts_owner_created_idx
  ON artifacts(tenant_id,owner_id,created_at DESC,id DESC);
CREATE INDEX artifacts_conversation_idx
  ON artifacts(tenant_id,owner_id,conversation_id,created_at DESC,id DESC);
CREATE UNIQUE INDEX artifacts_revision_idx
  ON artifacts(
    tenant_id,owner_id,COALESCE(workspace_id,''),
    COALESCE(conversation_id,''),name,revision
  );
ALTER TABLE artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE artifacts FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON artifacts
  USING (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
"""

_DOWN = "DROP TABLE IF EXISTS artifacts;"


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
