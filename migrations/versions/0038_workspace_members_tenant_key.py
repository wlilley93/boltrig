"""workspace_members: put tenant_id in the KEY (cross-tenant membership write).

`workspace_members` was keyed `(workspace_id, user_id)`. That is only safe if a
workspace id identifies exactly one workspace globally, and it does not:
`workspaces` is keyed `(tenant_id, id)`, so ids are unique only WITHIN an org,
and provisioning mints the SAME id (`ws_default`) for every org. The collision is
therefore guaranteed by construction, not merely possible.

Consequence before this migration: org B adding a user to ITS `ws_default` hit
`ON CONFLICT (workspace_id, user_id)` against org A's row and ran the DO UPDATE
arm, rewriting that user's `role` and `permissions` inside ORG A's workspace -
a cross-tenant privilege change. `tenant_id` was not in the SET list, so the row
stayed attributed to A and org B's own membership never materialised: the write
both corrupted another org and silently failed for the caller.

RLS would have turned this into an error rather than a cross-tenant write, but
RLS is opt-in (`BOLTRIG_RLS`) and was UNSET on every deployment checked, so the
fence was not standing.

The rekey is data-preserving. Rows whose (workspace_id, user_id) pair repeats
across tenants cannot exist under the OLD key, so there is nothing to
de-duplicate: the old primary key guaranteed at most one row per pair.

Revision ID: 0038_workspace_members_tenant_key
Revises: 0037_secure_input
"""

from __future__ import annotations

from alembic import op

revision = "0038_workspace_members_tenant_key"
down_revision = "0037_secure_input"
branch_labels = None
depends_on = None

# Idempotent, matching the house style: a fresh database already gets the correct
# key from the schema.sql baseline replay, so this must be a no-op there.
#
# Schema-RELATIVE (`to_regclass('workspace_members')`, not `'public.…'`): the
# migration-parity harness applies this SQL inside a NAMED schema via
# search_path, so a hardcoded `public.` resolves to NULL there and the whole
# block silently returns having done nothing. That is how the parity gate
# caught an earlier draft of this migration.
_UP = """
DO $$
DECLARE
    pk_name text;
BEGIN
    IF to_regclass('workspace_members') IS NULL THEN
        RETURN;
    END IF;

    SELECT conname INTO pk_name
      FROM pg_constraint
     WHERE conrelid = 'workspace_members'::regclass
       AND contype = 'p';

    -- Already keyed by all three columns (fresh baseline): nothing to do.
    IF pk_name IS NOT NULL AND (
        SELECT count(*)
          FROM unnest(
                 (SELECT conkey FROM pg_constraint WHERE conname = pk_name
                   AND conrelid = 'workspace_members'::regclass)
               ) AS attnum
    ) = 3 THEN
        RETURN;
    END IF;

    IF pk_name IS NOT NULL THEN
        EXECUTE format(
            'ALTER TABLE workspace_members DROP CONSTRAINT %I', pk_name
        );
    END IF;

    ALTER TABLE workspace_members
        ADD PRIMARY KEY (tenant_id, workspace_id, user_id);
END $$;
"""

_DOWN = """
DO $$
DECLARE
    pk_name text;
BEGIN
    IF to_regclass('workspace_members') IS NULL THEN
        RETURN;
    END IF;
    SELECT conname INTO pk_name
      FROM pg_constraint
     WHERE conrelid = 'workspace_members'::regclass
       AND contype = 'p';
    IF pk_name IS NOT NULL THEN
        EXECUTE format(
            'ALTER TABLE workspace_members DROP CONSTRAINT %I', pk_name
        );
    END IF;
    -- Narrowing the key back can fail if cross-tenant duplicates now exist,
    -- which is precisely the state the wide key was added to permit.
    ALTER TABLE workspace_members ADD PRIMARY KEY (workspace_id, user_id);
END $$;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
