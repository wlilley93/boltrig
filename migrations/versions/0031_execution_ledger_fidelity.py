"""Give the execution ledger the columns its records actually need.

The 0026 schema could not round-trip two shapes the domain models require, which
forced the durable adapter to infer them:

* ``runtime_identities`` had no principal column and no ``revoked_at``, so the
  principal was folded into the ``profile`` JSONB and ``updated_at`` was
  overloaded to carry the revocation time.
* ``execution_outbox`` kept only the materialized ``available_at``, so the
  requested value an ``OutboxIntent`` submitted was lost and command replay had
  to reverse the clamp to guess whether two appends differed.

Both are now first-class columns, so the durable adapter stores what it is given
and compares it exactly, matching the in-memory adapter with no inference.

``execution_outbox.intent_ordinal`` closes the same gap from the other side.
``AtomicEventAppend.outbox`` is an order-sensitive tuple, so the memory adapter
replays an identical resubmission and conflicts a reordered one; rows have no
inherent order, so without an ordinal the durable adapter would have to
reconstruct the tuple sorted by id and would answer both of those cases wrongly.

Revision ID: 0031_execution_ledger_fidelity
Revises: 0030_capability_attestations
"""

from __future__ import annotations

from alembic import op

revision = "0031_execution_ledger_fidelity"
down_revision = "0030_capability_attestations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE runtime_identities
            ADD COLUMN IF NOT EXISTS principal_user_id TEXT,
            ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ
        """
    )
    # Defensive: recover the principal any interim row folded into profile JSONB.
    op.execute(
        """
        UPDATE runtime_identities
        SET principal_user_id = profile ->> 'principal_user_id'
        WHERE principal_user_id IS NULL
          AND profile ->> 'principal_user_id' IS NOT NULL
        """
    )
    op.execute(
        "ALTER TABLE runtime_identities ALTER COLUMN principal_user_id SET NOT NULL"
    )
    op.execute(
        """
        ALTER TABLE execution_outbox
            ADD COLUMN IF NOT EXISTS requested_available_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS intent_ordinal INT
        """
    )
    # The materialized value is max(requested, now), so it is the tightest
    # available stand-in for rows written before the requested value was kept.
    op.execute(
        """
        UPDATE execution_outbox
        SET requested_available_at = available_at
        WHERE requested_available_at IS NULL
        """
    )
    # Interim rows were reconstructed into a tuple sorted by id, so ranking by id
    # reproduces exactly the order those rows already replayed with.
    op.execute(
        """
        UPDATE execution_outbox AS target
        SET intent_ordinal = ranked.position
        FROM (
            SELECT tenant_id, workspace_id, root_run_id, id,
                   ROW_NUMBER() OVER (
                       PARTITION BY tenant_id, workspace_id, root_run_id, event_sequence
                       ORDER BY id
                   ) - 1 AS position
            FROM execution_outbox
        ) AS ranked
        WHERE target.tenant_id = ranked.tenant_id
          AND target.workspace_id = ranked.workspace_id
          AND target.root_run_id = ranked.root_run_id
          AND target.id = ranked.id
          AND target.intent_ordinal IS NULL
        """
    )
    op.execute(
        "ALTER TABLE execution_outbox ALTER COLUMN requested_available_at SET NOT NULL"
    )
    op.execute("ALTER TABLE execution_outbox ALTER COLUMN intent_ordinal SET NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE execution_outbox DROP COLUMN IF EXISTS intent_ordinal")
    op.execute("ALTER TABLE execution_outbox DROP COLUMN IF EXISTS requested_available_at")
    op.execute("ALTER TABLE runtime_identities DROP COLUMN IF EXISTS revoked_at")
    op.execute("ALTER TABLE runtime_identities DROP COLUMN IF EXISTS principal_user_id")
