"""Capability doctrine step 2: the multi-binding capability shard.

Four new tables, no existing table altered:

  provider_connections  an authenticated instance that can perform work. The
                        ROUTING identity, deliberately without the
                        one-live-connection-per-adapter uniqueness that
                        integration_connections carries - three live CRMs is the
                        doctrine's worked example (SPEC §11.2, §11.3).
  source_operations     what a provider actually exposes, verbatim and
                        provider-prefixed; never model-facing.
  capability_bindings   "this source operation, through this connection,
                        implements crm.contact.search@1". binding_id is its own
                        identity, so a SECOND binding for one capability coexists
                        with the first instead of replacing it - the single-
                        binding contract that SPEC §11.1 measured.
  routing_policies      "under these circumstances select this binding", scoped
                        tenant-wide or per workspace, per operation class.

verb_bindings is untouched and keeps its (verb_id, tenant_id) key: it now means
"which adapter executes this SOURCE OPERATION", which is 1:1 and correct. The
plural layer is the capability, not the verb (decision 0036).

Additive only. ``store/schema.sql`` is edited in lockstep (the migration-parity
test compares both paths) and ``store/rls.sql`` fences all four.

Revision ID: 0079_capability_routing_shard
Revises: 0078_capability_presentation_fields
"""

from __future__ import annotations

from alembic import op

revision = "0079_capability_routing_shard"
down_revision = "0078_capability_presentation_fields"
branch_labels = None
depends_on = None


TABLES = """
-- Capability doctrine step 2 (docs/SPEC-capability-doctrine.md §8): the
-- multi-binding layer. A canonical capability may have MANY bindings; identity
-- is binding_id, so a second binding never replaces a first. verb_bindings keeps
-- its (verb_id, tenant_id) key and its meaning narrows to what it is actually
-- correct for: which adapter executes one SOURCE OPERATION.
CREATE TABLE IF NOT EXISTS provider_connections (
    id                 TEXT NOT NULL,
    tenant_id          TEXT NOT NULL,
    label              TEXT NOT NULL,          -- the destination a human recognises
    provider           TEXT NOT NULL,
    source_type        TEXT NOT NULL DEFAULT 'native' CHECK (source_type IN (
                         'nango','mcp','openapi','sdk_plugin','native')),
    adapter_id         TEXT,                   -- executing adapter, when there is one
    integration_connection_id TEXT,            -- catalogue row; label authority
    workspace_id       TEXT,                   -- NULL = tenant-wide
    account_ref        TEXT,
    credential_ref     TEXT,                   -- reference only, never material
    health             TEXT NOT NULL DEFAULT 'unknown' CHECK (health IN (
                         'unknown','pending','ok','degraded','down','revoked')),
    status             TEXT NOT NULL DEFAULT 'active' CHECK (status IN (
                         'active','disabled','revoked')),
    trust_level        TEXT NOT NULL DEFAULT 'untrusted' CHECK (trust_level IN (
                         'untrusted','reviewed','trusted','first_party')),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
-- DELIBERATELY NOT UNIQUE on (tenant_id, adapter_id): three live HubSpot
-- connections is the doctrine's worked example. The one-active-adapter index on
-- integration_connections constrains the CATALOGUE setup flow only (SPEC §11.2).
CREATE INDEX IF NOT EXISTS provider_connections_provider_idx
  ON provider_connections (tenant_id, provider, status);

CREATE TABLE IF NOT EXISTS source_operations (
    id                 TEXT NOT NULL,          -- provider-prefixed, never model-facing
    tenant_id          TEXT NOT NULL,
    provider           TEXT NOT NULL,
    source_type        TEXT NOT NULL DEFAULT 'native' CHECK (source_type IN (
                         'nango','mcp','openapi','sdk_plugin','native')),
    connection_id      TEXT,
    title              TEXT,
    description        TEXT NOT NULL DEFAULT '',
    input_schema       JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_schema      JSONB,
    annotations        JSONB NOT NULL DEFAULT '{}'::jsonb,
    schema_digest      TEXT NOT NULL DEFAULT '',
    catalogue_revision TEXT,
    consequence_hint   TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS source_operations_connection_idx
  ON source_operations (tenant_id, connection_id);

CREATE TABLE IF NOT EXISTS capability_bindings (
    binding_id           TEXT NOT NULL,
    tenant_id            TEXT NOT NULL,
    capability_id        TEXT NOT NULL,
    capability_version   INT NOT NULL DEFAULT 1,
    source_operation_id  TEXT NOT NULL,
    connection_id        TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN (
                           'proposed','approved','disabled','retired')),
    trust_level          TEXT NOT NULL DEFAULT 'untrusted' CHECK (trust_level IN (
                           'untrusted','reviewed','trusted','first_party')),
    priority             INT NOT NULL DEFAULT 100,
    workspace_predicate  TEXT,
    input_transform_ref  TEXT,
    output_transform_ref TEXT,
    source_schema_digest TEXT,
    consequence_override TEXT CHECK (consequence_override IN ('low','high')),
    health               TEXT NOT NULL DEFAULT 'unknown',
    fallback_policy      TEXT NOT NULL DEFAULT 'none',
    created_from         TEXT NOT NULL DEFAULT 'manual' CHECK (created_from IN (
                           'declared','mapping_pack','structural','ai_assisted','manual')),
    reviewed_by          TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, binding_id),
    FOREIGN KEY (tenant_id, connection_id)
      REFERENCES provider_connections(tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, source_operation_id)
      REFERENCES source_operations(tenant_id, id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS capability_bindings_capability_idx
  ON capability_bindings (tenant_id, capability_id, capability_version, priority);
-- One claim per (capability version, connection, source operation): a re-import
-- updates the binding it already made instead of growing a duplicate route.
CREATE UNIQUE INDEX IF NOT EXISTS capability_bindings_claim_idx
  ON capability_bindings (
    tenant_id, capability_id, capability_version, connection_id, source_operation_id
  ) WHERE status <> 'retired';

CREATE TABLE IF NOT EXISTS routing_policies (
    id                 TEXT NOT NULL,
    tenant_id          TEXT NOT NULL,
    capability_id      TEXT NOT NULL,
    binding_id         TEXT NOT NULL,
    operation_class    TEXT NOT NULL DEFAULT 'create' CHECK (operation_class IN (
                         'read','create','update','delete')),
    capability_version INT,                     -- NULL = any version
    scope              TEXT NOT NULL DEFAULT 'tenant' CHECK (scope IN (
                         'tenant','workspace')),
    workspace_id       TEXT,
    precedence         INT NOT NULL DEFAULT 100,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    CHECK ((scope = 'workspace') = (workspace_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS routing_policies_capability_idx
  ON routing_policies (tenant_id, capability_id, operation_class, precedence);
"""


def upgrade() -> None:
    op.execute(TABLES)


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS routing_policies;
        DROP TABLE IF EXISTS capability_bindings;
        DROP TABLE IF EXISTS source_operations;
        DROP TABLE IF EXISTS provider_connections;
        """
    )
