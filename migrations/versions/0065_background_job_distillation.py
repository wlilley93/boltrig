"""Admit `distillation` to the background-job receipt check constraint.

Revision ID: 0065_background_job_distillation
Revises: 0064_mcp_registration_revision

BACKGROUND_JOB_NAMES gained "distillation" so the session-distillation sweep could
record durable progress and appear on /readyz. The Python tuple was not enough:
`background_job_receipts` carries a CHECK that enumerates the names independently,
so every write was refused at the database with

    CheckViolationError: new row for relation "background_job_receipts"
    violates check constraint "background_job_receipts_job_name_check"

and, because attempt recording is deliberately best-effort, the sweep carried on
while its evidence silently never existed. /readyz would have shown
`attempt_evidence_not_observed` forever - which reads as "nothing has happened
yet", not "the write is broken". That is precisely the failure the whole
progress-reporting effort exists to remove, reproduced inside it.

The in-memory store has no constraint, so unit tests passed throughout. Only the
deployment showed it.
"""

from __future__ import annotations

from alembic import op

revision = "0065_background_job_distillation"
down_revision = "0064_mcp_registration_revision"
branch_labels = None
depends_on = None

_CONSTRAINT = "background_job_receipts_job_name_check"


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE background_job_receipts DROP CONSTRAINT IF EXISTS {_CONSTRAINT}"
    )
    op.execute(
        f"""ALTER TABLE background_job_receipts ADD CONSTRAINT {_CONSTRAINT}
            CHECK (job_name IN ('hitl_expiry','retention','distillation'))"""
    )


def downgrade() -> None:
    # Rows for the removed name must go first or the constraint cannot be
    # re-applied - a downgrade that leaves the table unconstrained would be worse
    # than one that loses evidence it is no longer allowed to hold.
    op.execute("DELETE FROM background_job_receipts WHERE job_name = 'distillation'")
    op.execute(
        f"ALTER TABLE background_job_receipts DROP CONSTRAINT IF EXISTS {_CONSTRAINT}"
    )
    op.execute(
        f"""ALTER TABLE background_job_receipts ADD CONSTRAINT {_CONSTRAINT}
            CHECK (job_name IN ('hitl_expiry','retention'))"""
    )
