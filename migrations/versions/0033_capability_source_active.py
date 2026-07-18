"""Scoped-declarative capability reconciliation: is_active + source provenance.

Binding court order [2026] LEXBY LOG-2026-07-17-120214. ``agent_capabilities``
gains two columns so a manifest can be DECLARATIVE over the capabilities it
authored and ADDITIVE over governed control-plane grants:

* ``is_active`` - a soft-active flag. ``list_capabilities`` returns only active
  rows, so a deactivated capability can never be selected for routing.
* ``source`` - provenance, 'manifest' | 'control-plane'. Only 'manifest' rows are
  ever reconciled; 'control-plane' rows (minted by ``control.capability.upsert``)
  are only ever added.

The ``source`` backfill default is DELIBERATELY 'control-plane' and fail-safe:
pre-existing rows have unknown provenance, so the first post-migration apply must
NOT mass-deactivate them (only 'manifest' rows are reconciled). New rows written
by a manifest apply stamp 'manifest' explicitly.

Revision ID: 0033_capability_source_active
Revises: 0032_assignment_attestation_set
"""

from __future__ import annotations

from alembic import op

revision = "0033_capability_source_active"
down_revision = "0032_assignment_attestation_set"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE agent_capabilities
            ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true
        """
    )
    op.execute(
        """
        ALTER TABLE agent_capabilities
            ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'control-plane'
                CHECK (source IN ('manifest', 'control-plane'))
        """
    )


def downgrade() -> None:
    # Dropping the column drops its inline CHECK with it.
    op.execute("ALTER TABLE agent_capabilities DROP COLUMN IF EXISTS source")
    op.execute("ALTER TABLE agent_capabilities DROP COLUMN IF EXISTS is_active")
