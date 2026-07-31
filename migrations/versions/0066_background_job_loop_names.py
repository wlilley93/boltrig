"""Admit `anchor`, `workflow_scheduler` and `pump` to the background-job CHECK.

Revision ID: 0066_background_job_loop_names
Revises: 0065_background_job_distillation

Three more loops now publish durable progress, so `background_job_receipts` must
accept their names. The table's CHECK enumerates them INDEPENDENTLY of
BACKGROUND_JOB_NAMES, and on 2026-07-30 the Python tuple was widened without the
constraint: every write was refused at the database, and because attempt recording
is deliberately best-effort the sweeps carried on while their evidence silently
never existed. tests/security/test_background_job_health.py now compares the two
enumerations so they cannot drift again, which is what caught the need for this.

ORDERING THAT MATTERS, and the reason this is a separate migration from 0065.
Adding a job name is NOT backward compatible: a kernel build that predates the
name raises mapping the row and loses the WHOLE readiness read, not just that row.
The tolerant reader was deployed on 2026-07-31 09:19 BEFORE these names were
introduced, so no running kernel can be broken by the first row carrying one.

The DB must reach this revision BEFORE any image asserting
EXPECTED_ALEMBIC_HEAD = 0066 is deployed, or /readyz returns 503 head_mismatch -
which is exactly what an out-of-order deploy of 0065 produced earlier that day.
"""

from __future__ import annotations

from alembic import op

revision = "0066_background_job_loop_names"
down_revision = "0065_background_job_distillation"
branch_labels = None
depends_on = None

_CONSTRAINT = "background_job_receipts_job_name_check"
_NAMES = (
    "hitl_expiry",
    "retention",
    "distillation",
    "anchor",
    "workflow_scheduler",
    "pump",
)
_PRIOR = ("hitl_expiry", "retention", "distillation")


def _enumerated(names: tuple[str, ...]) -> str:
    return ",".join(f"'{name}'" for name in names)


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE background_job_receipts DROP CONSTRAINT IF EXISTS {_CONSTRAINT}"
    )
    op.execute(
        f"""ALTER TABLE background_job_receipts ADD CONSTRAINT {_CONSTRAINT}
            CHECK (job_name IN ({_enumerated(_NAMES)}))"""
    )


def downgrade() -> None:
    # Rows for the removed names must go first or the narrower constraint cannot be
    # applied. Losing evidence the table is no longer permitted to hold beats
    # leaving it unconstrained, which is how the names drifted in the first place.
    removed = tuple(name for name in _NAMES if name not in _PRIOR)
    op.execute(
        "DELETE FROM background_job_receipts WHERE job_name IN "
        f"({_enumerated(removed)})"
    )
    op.execute(
        f"ALTER TABLE background_job_receipts DROP CONSTRAINT IF EXISTS {_CONSTRAINT}"
    )
    op.execute(
        f"""ALTER TABLE background_job_receipts ADD CONSTRAINT {_CONSTRAINT}
            CHECK (job_name IN ({_enumerated(_PRIOR)}))"""
    )
