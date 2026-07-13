"""Reconcile Alembic head with the bootstrap schema.

The original baseline followed the mutable ``store/schema.sql`` file, which
hid changes that had no ordered revision. Revision 0001 is now immutable; this
migration records those previously implicit changes so an upgrade from the
historical baseline and a fresh bootstrap have the same PostgreSQL catalogue.

Revision ID: 0022_schema_parity
Revises: 0021_work_items_run_lookup
"""

from __future__ import annotations

from alembic import op

revision = "0022_schema_parity"
down_revision = "0021_work_items_run_lookup"
branch_labels = None
depends_on = None

_DDL = r"""
CREATE EXTENSION IF NOT EXISTS vector;

-- SEC-14 columns landed in the bootstrap before they had an ordered revision.
ALTER TABLE hitl_requests ADD COLUMN IF NOT EXISTS verb TEXT;
ALTER TABLE hitl_requests ADD COLUMN IF NOT EXISTS requested_by TEXT;

-- Decision 0003 channel state. `channels` is deliberately resolvable before a
-- tenant is bound; bindings and pairings remain tenant-scoped.
CREATE TABLE IF NOT EXISTS channels (
    id                 TEXT PRIMARY KEY,
    tenant_id          TEXT NOT NULL,
    platform           TEXT NOT NULL,
    name               TEXT NOT NULL,
    transport          TEXT NOT NULL,
    credential_ref     TEXT,
    config             JSONB NOT NULL DEFAULT '{}'::jsonb,
    unpaired_behavior  TEXT NOT NULL DEFAULT 'reject',
    enabled            BOOLEAN NOT NULL DEFAULT true,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS channels_tenant_idx ON channels (tenant_id);

CREATE TABLE IF NOT EXISTS channel_bindings (
    id                TEXT NOT NULL,
    tenant_id         TEXT NOT NULL,
    channel_id        TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    platform          TEXT NOT NULL,
    external_user_id  TEXT NOT NULL,
    subject           TEXT NOT NULL,
    role              TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE UNIQUE INDEX IF NOT EXISTS channel_bindings_sender_idx
    ON channel_bindings (tenant_id, channel_id, external_user_id);

CREATE TABLE IF NOT EXISTS channel_pairings (
    id                TEXT NOT NULL,
    tenant_id         TEXT NOT NULL,
    channel_id        TEXT NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    code_hash         TEXT NOT NULL,
    external_user_id  TEXT NOT NULL,
    subject           TEXT NOT NULL,
    role              TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending',
    attempts          INTEGER NOT NULL DEFAULT 0,
    expires_at        TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS channel_pairings_code_idx
    ON channel_pairings (tenant_id, channel_id, code_hash);

CREATE TABLE IF NOT EXISTS memory_projection_statuses (
    id             TEXT NOT NULL,
    tenant_id      TEXT NOT NULL,
    projection_id  TEXT NOT NULL,
    operation      TEXT NOT NULL CHECK (operation IN ('remember', 'forget')),
    status         TEXT NOT NULL CHECK (
        (operation = 'remember' AND status IN ('pending', 'written', 'failed'))
        OR (operation = 'forget' AND status IN ('pending', 'deleted', 'delete_failed'))
    ),
    fact_id        TEXT,
    target         TEXT,
    projection_ref TEXT,
    error          TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS memory_projection_statuses_fact_idx
    ON memory_projection_statuses (tenant_id, fact_id, projection_id);

CREATE TABLE IF NOT EXISTS memory_vectors (
    tenant_id   TEXT NOT NULL,
    id          TEXT NOT NULL,
    owner_scope TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'entity',
    content     TEXT NOT NULL DEFAULT '',
    data_class  TEXT NOT NULL DEFAULT 'standard',
    source_kind TEXT NOT NULL DEFAULT 'verb_result',
    source_ref  TEXT,
    embedding   vector(256),
    weight      DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS memory_vectors_scope_idx
    ON memory_vectors (tenant_id, owner_scope, kind);

CREATE TABLE IF NOT EXISTS memory_vector_edges (
    tenant_id TEXT NOT NULL,
    src       TEXT NOT NULL,
    dst       TEXT NOT NULL,
    PRIMARY KEY (tenant_id, src, dst)
);

-- Round Four used CREATE TABLE IF NOT EXISTS against a smaller pre-existing
-- users table, so its extra columns and TEXT[] group type were never applied.
CREATE OR REPLACE FUNCTION pg_temp._boltrig_jsonb_text_array(value JSONB)
RETURNS TEXT[]
LANGUAGE SQL
IMMUTABLE
AS $function$
    SELECT COALESCE(array_agg(item), ARRAY[]::TEXT[])
    FROM jsonb_array_elements_text(COALESCE(value, '[]'::JSONB)) AS elements(item);
$function$;

DO $migration$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'users'
          AND column_name = 'groups'
          AND data_type = 'jsonb'
    ) THEN
        ALTER TABLE users ALTER COLUMN groups DROP DEFAULT;
        ALTER TABLE users ALTER COLUMN groups TYPE TEXT[]
            USING pg_temp._boltrig_jsonb_text_array(groups);
    ELSIF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'users'
          AND column_name = 'groups'
          AND data_type = 'ARRAY'
          AND udt_name = '_text'
    ) THEN
        -- A partially reconciled deployment may already have TEXT[] while the
        -- historical nullable rows remain. A same-type rewrite normalises NULL
        -- without an UPDATE that could be filtered by FORCE RLS.
        ALTER TABLE users ALTER COLUMN groups DROP DEFAULT;
        ALTER TABLE users ALTER COLUMN groups TYPE TEXT[]
            USING COALESCE(groups, ARRAY[]::TEXT[]);
    END IF;
END
$migration$;

ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'none';
ALTER TABLE users ADD COLUMN IF NOT EXISTS scope JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE users ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE users ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'idp';
ALTER TABLE users ADD COLUMN IF NOT EXISTS source_group TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ;
ALTER TABLE users ALTER COLUMN groups SET DEFAULT '{}'::TEXT[];
ALTER TABLE users ALTER COLUMN groups SET NOT NULL;
ALTER TABLE users DROP COLUMN IF EXISTS updated_at;
DROP FUNCTION pg_temp._boltrig_jsonb_text_array(JSONB);

-- Preserve an already-enabled RLS posture across this upgrade. A fresh Alembic
-- or schema.sql bootstrap intentionally remains policy-free until the explicit
-- rls.sql overlay is applied; an existing RLS deployment, however, must never
-- gain unfenced tenant tables merely because they were introduced by a revision.
DO $migration$
DECLARE
    t TEXT;
    scoped TEXT[] := ARRAY[
        'channel_bindings',
        'channel_pairings',
        'memory_projection_statuses',
        'memory_vectors',
        'memory_vector_edges'
    ];
    rls_was_enabled BOOLEAN;
BEGIN
    SELECT c.relrowsecurity
      INTO rls_was_enabled
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = current_schema()
       AND c.relname = 'nouns';

    IF COALESCE(rls_was_enabled, false) THEN
        FOREACH t IN ARRAY scoped LOOP
            EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
            EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
            EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
            EXECUTE format(
                'CREATE POLICY tenant_isolation ON %I '
                'USING (tenant_id = current_setting(''app.tenant_id'', true)) '
                'WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))',
                t
            );
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'boltrig_app') THEN
                EXECUTE format(
                    'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE %I TO boltrig_app',
                    t
                );
            END IF;
        END LOOP;
    END IF;
END
$migration$;
"""


def upgrade() -> None:
    op.execute(_DDL)


def downgrade() -> None:
    raise NotImplementedError(
        "0022 reconciles objects that may predate Alembic; destructive downgrade is unsafe"
    )
