"""users: carry the forced-rotation flag for a provisioning credential.

[2026] VJS-COUNTY 8, D7 ordered the founding superadmin seeded into a default org
plus workspace AND "a password rotation forced before prod exposure, so a weak
seed admin is never the live prod gate". The first half shipped; the second was
never built, and nothing noticed until the order-binding gate tried to bind D7 and
could not.

The gap was not that the seed password is weak - `boltrig initiate` already
refuses one through `validate_password_strength`. It is that the credential typed
at provisioning time survives as the live credential. That password has been in a
shell history, very often in a runbook or a provisioning script, and frequently in
more than one person's hands; strength does not touch any of that.

Additive, defaulted, backfilled FALSE. Every user that already exists is
completely unaffected, which is deliberate and not merely convenient: D7 is about
the SEEDING flow, and turning this on retroactively would lock live operators out
of two production consoles for a hazard their accounts do not have.

Revision ID: 0039_user_must_change_password
Revises: 0038_workspace_members_tenant_key
"""

from __future__ import annotations

from alembic import op

revision = "0039_user_must_change_password"
down_revision = "0038_workspace_members_tenant_key"
branch_labels = None
depends_on = None

# Idempotent and schema-RELATIVE, matching the house style: a fresh database gets
# the column from the schema.sql baseline replay, so this must be a no-op there,
# and `to_regclass('users')` (not `'public.users'`) because the migration-parity
# harness applies this SQL inside a NAMED schema via search_path - a hardcoded
# `public.` resolves to NULL there and the block silently does nothing.
_UP = """
DO $$
BEGIN
    IF to_regclass('users') IS NOT NULL THEN
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE;
    END IF;
END $$;
"""

_DOWN = """
DO $$
BEGIN
    IF to_regclass('users') IS NOT NULL THEN
        ALTER TABLE users DROP COLUMN IF EXISTS must_change_password;
    END IF;
END $$;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
