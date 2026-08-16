"""Bounded read-only file metadata listing device verb.

Revision ID: 0072_device_workspace_snapshots
Revises: 0071_model_endpoint_revision
"""

from __future__ import annotations

from alembic import op

revision = "0072_device_workspace_snapshots"
down_revision = "0071_model_endpoint_revision"
branch_labels = None
depends_on = None


_OLD_VERBS = (
    "device.file.read",
    "device.file.write",
    "device.command.run",
)
_NEW_VERBS = (
    "device.file.list",
    "device.file.read",
    "device.file.write",
    "device.command.run",
)


def _constraint(verbs: tuple[str, ...]) -> str:
    values = ",".join(f"'{verb}'" for verb in verbs)
    return (
        "ALTER TABLE device_leases ADD CONSTRAINT "
        f"device_lease_verb_valid CHECK (verb IN ({values}))"
    )


def upgrade() -> None:
    op.execute(
        "ALTER TABLE device_leases DROP CONSTRAINT IF EXISTS "
        "device_lease_verb_valid"
    )
    op.execute(_constraint(_NEW_VERBS))


def downgrade() -> None:
    # Refuse an unsafe downgrade while rows using the added contracts remain.
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM device_leases WHERE verb IN "
        "('device.file.list')) THEN "
        "RAISE EXCEPTION 'device workspace snapshot leases still exist'; "
        "END IF; END $$"
    )
    op.execute(
        "ALTER TABLE device_leases DROP CONSTRAINT IF EXISTS "
        "device_lease_verb_valid"
    )
    op.execute(_constraint(_OLD_VERBS))
