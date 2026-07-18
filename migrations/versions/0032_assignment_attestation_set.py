"""Persist the capability-attestation set reference with its assignment.

``AssignmentCapabilityAttestationPin`` is documented as a small value persisted
with an assignment, but ``execution_assignments`` had nowhere to put it, so the
pin had no durable home and the doctrine was false through two deferrals.

Only ONE column is added, not one per pin field.  A pin names an attestation set
by its binding, its authority evaluation, and the catalog and set digests; the
binding and the authority are already constituents of the assignment row
(tenant/workspace/root-run/phase/id, and the ``authority`` JSONB), so storing
them again would let a row carry a binding that names a *different* assignment's
attestation set.  The row therefore keeps only the three irreducible digests
(``AttestationSetRef``), and the pin's binding and authority are derived from
the record by ``AssignmentCapabilityAttestationPin.from_assignment``.  The
mismatch is not detected, it is unconstructable.

The column is nullable with no default: an assignment cut before any attestation
set was written for it simply has no reference, which is exactly what NULL says.

Revision ID: 0032_assignment_attestation_set
Revises: 0031_execution_ledger_fidelity
"""

from __future__ import annotations

from alembic import op

revision = "0032_assignment_attestation_set"
down_revision = "0031_execution_ledger_fidelity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE execution_assignments
            ADD COLUMN IF NOT EXISTS attestation_set JSONB
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE execution_assignments DROP COLUMN IF EXISTS attestation_set")
