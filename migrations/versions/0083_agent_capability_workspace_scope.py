"""Per-workspace agent rosters: an agent profile may belong to one workspace.

One account can run two businesses. The organisation is the tenant; a workspace
is a scope inside it ([2026] VJS-COUNTY 8, D4). Until now an agent capability
profile was a tenant-wide library record, so both businesses shared one roster
and one set of familiars.

  agent_capabilities.workspace_id   the workspace the profile belongs to, or
                                    NULL for an ORG-WIDE profile every workspace
                                    sees.

NULL is the default and every pre-existing row keeps it, which is exactly what
those rows already were. A workspace read is the UNION of its own rows and the
org-wide ones, so a shared agent is declared once rather than copied per
workspace.

THE PRIMARY KEY IS REPLACED BY AN EXPRESSION UNIQUE INDEX, and that is the whole
point of the change: PRIMARY KEY (tenant_id, name) forbids two workspaces from
each having a "researcher", which is the thing being asked for. Uniqueness still
has to hold WITHIN a scope, because the profile editor disables the name on edit
and ``select_capability`` matches on the bare name.

``coalesce(workspace_id, '')`` rather than the bare column because Postgres
treats NULLs as DISTINCT in a unique index: without it the org-wide scope would
admit unlimited duplicates of one name while every workspace scope was
constrained, which is the opposite of the intended shape. Same reasoning, same
form as ``entity_provenance_record_idx`` in 0082.

No table is dropped and no row is rewritten. ``store/schema.sql`` is edited in
lockstep (the migration-parity test compares both paths); ``store/rls.sql``
already fences this table by tenant.

Revision ID: 0083_agent_capability_workspace_scope
Revises: 0082_entity_provenance
"""

from __future__ import annotations

from alembic import op

revision = "0083_agent_capability_workspace_scope"
down_revision = "0082_entity_provenance"
branch_labels = None
depends_on = None


UPGRADE = """
ALTER TABLE agent_capabilities ADD COLUMN IF NOT EXISTS workspace_id TEXT;

ALTER TABLE agent_capabilities DROP CONSTRAINT IF EXISTS agent_capabilities_pkey;

CREATE UNIQUE INDEX IF NOT EXISTS agent_capabilities_scope_idx
  ON agent_capabilities (tenant_id, coalesce(workspace_id, ''), name);
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    # Reinstating the primary key requires every name to be unique tenant-wide
    # again, so a downgrade after a second workspace has authored a colliding
    # name cannot succeed. That is correct: the rollback is a restore, not a
    # DDL reversal (the same rule that governs 0022_schema_parity).
    op.execute(
        """
        DROP INDEX IF EXISTS agent_capabilities_scope_idx;
        ALTER TABLE agent_capabilities
          ADD CONSTRAINT agent_capabilities_pkey PRIMARY KEY (tenant_id, name);
        ALTER TABLE agent_capabilities DROP COLUMN IF EXISTS workspace_id;
        """
    )
