"""Admit `reflection` to the background-job CHECK.

Revision ID: 0067_background_job_reflection
Revises: 0066_background_job_loop_names

Task #29: reflection had NEVER written a memory row anywhere, and nothing could
say whether that was idle (no terminal work items, or the feature disabled) or
broken (every attempt failing inside a best-effort swallow at DEBUG). The pump
now publishes a `reflection` receipt per throughput window when reflection is
enabled, so the three states are distinguishable from the receipts alone.

Same ordering rule as 0066, for the same reason: adding a job name is NOT
backward compatible for a kernel build that predates it - the row mapping raises
and takes the WHOLE readiness read down. Every running kernel already carries
the tolerant reader (deployed 2026-07-31 09:19), and the DB must reach this
revision BEFORE any image asserting EXPECTED_ALEMBIC_HEAD = 0067 is deployed.
"""

from __future__ import annotations

from alembic import op

revision = "0067_background_job_reflection"
down_revision = "0066_background_job_loop_names"
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
    "reflection",
)
_PRIOR = tuple(name for name in _NAMES if name != "reflection")


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
    # Rows for the removed name must go first or the narrower constraint cannot
    # be applied (the 0066 rule, unchanged).
    op.execute(
        "DELETE FROM background_job_receipts WHERE job_name = 'reflection'"
    )
    op.execute(
        f"ALTER TABLE background_job_receipts DROP CONSTRAINT IF EXISTS {_CONSTRAINT}"
    )
    op.execute(
        f"""ALTER TABLE background_job_receipts ADD CONSTRAINT {_CONSTRAINT}
            CHECK (job_name IN ({_enumerated(_PRIOR)}))"""
    )
