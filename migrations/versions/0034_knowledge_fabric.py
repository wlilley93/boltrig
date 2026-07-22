"""Canonical Knowledge catalogue, object references, search, and projections.

Revision ID: 0034_knowledge_fabric
Revises: 0033_capability_source_active
"""

from __future__ import annotations

from alembic import op

revision = "0034_knowledge_fabric"
down_revision = "0033_capability_source_active"
branch_labels = None
depends_on = None

DDL = r"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS knowledge_uploads (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT,
    title TEXT NOT NULL, filename TEXT NOT NULL, media_type TEXT NOT NULL,
    owner_scope TEXT NOT NULL, source_kind TEXT NOT NULL, source_ref TEXT,
    staged_key TEXT, digest TEXT, byte_size BIGINT,
    status TEXT NOT NULL CHECK (status IN ('begun','staged','committed')),
    asset_id TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (tenant_id,id)
);
CREATE TABLE IF NOT EXISTS knowledge_blobs (
    tenant_id TEXT NOT NULL, digest TEXT NOT NULL, object_key TEXT NOT NULL,
    byte_size BIGINT NOT NULL, media_type TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,digest), UNIQUE (tenant_id,object_key)
);
CREATE TABLE IF NOT EXISTS knowledge_assets (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT,
    title TEXT NOT NULL, filename TEXT NOT NULL, asset_type TEXT NOT NULL,
    owner_scope TEXT NOT NULL, current_revision_id TEXT NOT NULL,
    source_kind TEXT NOT NULL, source_ref TEXT, deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (tenant_id,id)
);
CREATE TABLE IF NOT EXISTS knowledge_source_occurrences (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, asset_id TEXT NOT NULL,
    source_kind TEXT NOT NULL, external_id TEXT NOT NULL, external_path TEXT,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (tenant_id,id),
    FOREIGN KEY (tenant_id,asset_id) REFERENCES knowledge_assets(tenant_id,id)
      ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS knowledge_source_occurrences_asset_idx
  ON knowledge_source_occurrences(tenant_id,asset_id,observed_at);
CREATE TABLE IF NOT EXISTS knowledge_revisions (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, asset_id TEXT NOT NULL,
    blob_digest TEXT NOT NULL, version INT NOT NULL, media_type TEXT NOT NULL,
    byte_size BIGINT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,asset_id,version),
    FOREIGN KEY (tenant_id,asset_id) REFERENCES knowledge_assets(tenant_id,id)
      ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,blob_digest) REFERENCES knowledge_blobs(tenant_id,digest)
      ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS knowledge_representations (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, revision_id TEXT NOT NULL,
    kind TEXT NOT NULL, format TEXT NOT NULL, generator TEXT NOT NULL,
    generator_version TEXT NOT NULL, content_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (tenant_id,id),
    FOREIGN KEY (tenant_id,revision_id) REFERENCES knowledge_revisions(tenant_id,id)
      ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS knowledge_segments (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, asset_id TEXT NOT NULL,
    revision_id TEXT NOT NULL, representation_id TEXT NOT NULL,
    sequence INT NOT NULL, text TEXT NOT NULL, locator JSONB NOT NULL,
    content_hash TEXT NOT NULL,
    search_vector TSVECTOR GENERATED ALWAYS AS
      (to_tsvector('simple',coalesce(text,''))) STORED,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (tenant_id,id),
    UNIQUE (tenant_id,representation_id,sequence),
    FOREIGN KEY (tenant_id,asset_id) REFERENCES knowledge_assets(tenant_id,id)
      ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,revision_id) REFERENCES knowledge_revisions(tenant_id,id)
      ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,representation_id)
      REFERENCES knowledge_representations(tenant_id,id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS knowledge_segments_search_idx
  ON knowledge_segments USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS knowledge_segments_asset_idx
  ON knowledge_segments(tenant_id,asset_id,sequence);
CREATE TABLE IF NOT EXISTS knowledge_embeddings (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL, model_provider TEXT NOT NULL, model_name TEXT NOT NULL,
    model_version TEXT NOT NULL, dimensions INT NOT NULL, distance_metric TEXT NOT NULL,
    vector vector(256) NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,id),
    UNIQUE (tenant_id,subject_id,model_provider,model_name,model_version),
    FOREIGN KEY (tenant_id,subject_id) REFERENCES knowledge_segments(tenant_id,id)
      ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS knowledge_embeddings_subject_idx
  ON knowledge_embeddings(tenant_id,subject_type,subject_id);
CREATE TABLE IF NOT EXISTS knowledge_asset_access (
    tenant_id TEXT NOT NULL, asset_id TEXT NOT NULL, scope TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,asset_id,scope),
    FOREIGN KEY (tenant_id,asset_id) REFERENCES knowledge_assets(tenant_id,id)
      ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS knowledge_asset_access_scope_idx
  ON knowledge_asset_access(tenant_id,scope,asset_id);
CREATE TABLE IF NOT EXISTS knowledge_providers (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, display_name TEXT NOT NULL,
    role TEXT NOT NULL, enabled BOOLEAN NOT NULL, bundled BOOLEAN NOT NULL,
    health TEXT NOT NULL, status TEXT NOT NULL, last_error TEXT, config JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (tenant_id,id)
);
CREATE TABLE IF NOT EXISTS knowledge_projection_statuses (
    tenant_id TEXT NOT NULL, provider_id TEXT NOT NULL, subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL, operation TEXT NOT NULL, status TEXT NOT NULL,
    projection_ref TEXT, error TEXT, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,provider_id,subject_id,operation),
    FOREIGN KEY (tenant_id,provider_id) REFERENCES knowledge_providers(tenant_id,id)
      ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS knowledge_jobs (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, kind TEXT NOT NULL,
    subject_id TEXT NOT NULL, status TEXT NOT NULL, detail JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (tenant_id,id)
);
CREATE TABLE IF NOT EXISTS knowledge_projection_outbox (
    tenant_id TEXT NOT NULL, id TEXT NOT NULL, provider_id TEXT NOT NULL,
    subject_type TEXT NOT NULL, subject_id TEXT NOT NULL, operation TEXT NOT NULL,
    payload JSONB NOT NULL, status TEXT NOT NULL DEFAULT 'pending', attempts INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (tenant_id,id)
);
CREATE INDEX IF NOT EXISTS knowledge_projection_outbox_pending_idx
  ON knowledge_projection_outbox(tenant_id,status,created_at);
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS knowledge_projection_outbox;
        DROP TABLE IF EXISTS knowledge_jobs;
        DROP TABLE IF EXISTS knowledge_projection_statuses;
        DROP TABLE IF EXISTS knowledge_providers;
        DROP TABLE IF EXISTS knowledge_asset_access;
        DROP TABLE IF EXISTS knowledge_embeddings;
        DROP TABLE IF EXISTS knowledge_segments;
        DROP TABLE IF EXISTS knowledge_representations;
        DROP TABLE IF EXISTS knowledge_revisions;
        DROP TABLE IF EXISTS knowledge_source_occurrences;
        DROP TABLE IF EXISTS knowledge_assets;
        DROP TABLE IF EXISTS knowledge_blobs;
        DROP TABLE IF EXISTS knowledge_uploads;
        """
    )
