"""Capability doctrine step 3: opaque record references and their provenance.

One new table, no existing table altered.

  entity_provenance  what ``brref_contact_k3mq7ayt2xr`` actually means: the
                     connection, provider, remote object type, remote record
                     id, binding and capability version one record came from
                     (SPEC §3).

This is the record half of step 3. A fan-out read merges rows from several
connections into one answer, and the model must then be able to say "update
THAT one" without ever holding a HubSpot id or a provider prefix. The ref is
what it holds instead, and this table is what a ref resolves to.

The ref is minted RANDOM and stored, not derived from the record's identity.
``boltrig/models/provenance.py`` carries the reasoning: a derived ref is an
offline confirmation oracle for anyone who sees one, and a keyed derivation
buys a key to manage, which ``boltrig/kernel/audit.py`` shows the cost of.
Determinism instead comes from the unique index on the identity tuple, so a
second sighting returns the ref already minted.

Additive only. ``store/schema.sql`` is edited in lockstep (the migration-parity
test compares both paths) and ``store/rls.sql`` fences the table.

Revision ID: 0082_entity_provenance
Revises: 0081_merge_capability_and_integration_scope
"""

from __future__ import annotations

from alembic import op

revision = "0082_entity_provenance"
down_revision = "0081_merge_capability_and_integration_scope"
branch_labels = None
depends_on = None


TABLES = """
CREATE TABLE IF NOT EXISTS entity_provenance (
    ref                 TEXT NOT NULL,
    tenant_id           TEXT NOT NULL,
    entity_type         TEXT NOT NULL,
    connection_id       TEXT NOT NULL,
    provider            TEXT NOT NULL,
    remote_object_type  TEXT NOT NULL,
    remote_record_id    TEXT NOT NULL,
    capability_id       TEXT NOT NULL,
    capability_version  INT NOT NULL DEFAULT 1,
    binding_id          TEXT,
    workspace_id        TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, ref),
    FOREIGN KEY (tenant_id, connection_id)
      REFERENCES provider_connections(tenant_id, id) ON DELETE CASCADE
);

-- THIS INDEX IS THE IDEMPOTENCY. Re-observing a record updates last_seen_at and
-- returns the existing ref rather than naming one object twice; two refs for one
-- record makes a follow-up write ambiguous in exactly the way the ref exists to
-- prevent.
--
-- workspace_id is coalesced because Postgres treats NULLs as DISTINCT in a
-- unique index: without it, every tenant-wide sighting would mint a fresh ref
-- and the idempotency would silently hold only for workspace-scoped rows.
CREATE UNIQUE INDEX IF NOT EXISTS entity_provenance_record_idx
  ON entity_provenance (
    tenant_id, coalesce(workspace_id, ''), connection_id,
    remote_object_type, remote_record_id
  );
"""


def upgrade() -> None:
    op.execute(TABLES)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS entity_provenance;")
