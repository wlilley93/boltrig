"""Capability doctrine step 1: presentation fields on verb_bindings.

Adds nullable presentation/mapping columns so the model-facing name, the
canonical capability identity, the internal source-operation id and the
connection label can diverge from the stored verb_id without breaking storage
or the single-binding contract (which the multi-binding shard revisits):

  internal_source_operation_id  the raw provider-prefixed operation id
                                (today the verb_id itself; populated when the
                                capability compiler starts issuing mappings)
  canonical_capability_id       the canonical capability this binding
                                implements, e.g. crm.contact.search@1
  model_display_name            the name projected to the model once a
                                canonical mapping exists
  connection_label              presentation copy of the connection's
                                human-readable label; the authoritative label
                                stays on integration_connections.label

Additive only: every column is nullable, no enforcement site reads them, no
behaviour change. ``store/schema.sql`` is edited in lockstep (the
migration-parity test compares both paths). See
``docs/SPEC-capability-doctrine.md`` §10 step 1 and §11 (known gaps).

Revision ID: 0078_capability_presentation_fields
Revises: 0077_audit_outbox
"""

from __future__ import annotations

from alembic import op

revision = "0078_capability_presentation_fields"
down_revision = "0077_audit_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE verb_bindings
          ADD COLUMN IF NOT EXISTS internal_source_operation_id TEXT,
          ADD COLUMN IF NOT EXISTS canonical_capability_id TEXT,
          ADD COLUMN IF NOT EXISTS model_display_name TEXT,
          ADD COLUMN IF NOT EXISTS connection_label TEXT;

        CREATE INDEX IF NOT EXISTS verb_bindings_canonical_capability_idx
          ON verb_bindings (tenant_id, canonical_capability_id)
          WHERE canonical_capability_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS verb_bindings_canonical_capability_idx;

        ALTER TABLE verb_bindings
          DROP COLUMN IF EXISTS connection_label,
          DROP COLUMN IF EXISTS model_display_name,
          DROP COLUMN IF EXISTS canonical_capability_id,
          DROP COLUMN IF EXISTS internal_source_operation_id;
        """
    )
