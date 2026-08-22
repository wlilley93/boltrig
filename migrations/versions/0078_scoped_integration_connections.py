"""Per-user integration credentials: scope the one-active-connection rule.

Integration credentials were per-TENANT only. A partial unique index on
``(tenant_id, adapter_id)`` allowed exactly ONE active connection per adapter, so
two people could not each hold their own Jira token -- an org either shared a
service account or nobody connected at all. That index is the whole reason this
migration exists; everything else here is downstream of replacing it.

The scoping added is the one ``ai_configs`` has carried since 0013: a ``level``
and a ``scope_id``, where an org row's ``scope_id`` IS the tenant id. Resolution
then reads user-then-org, so a personal connection wins for that person's calls
and the org connection stays the fallback for everyone else.

``level`` is deliberately ``'org' | 'user'`` only, though ``ai_configs`` also
has ``'workspace'``. Two concrete things are missing rather than one philosophical
one: a workspace row needs a live ``get_workspace_member`` re-check at resolve
time, and ``Principal.context()`` does not set ``workspace_id`` at all, so the
HTTP connect path has no workspace to offer even if the resolver wanted one.

The backfill is safe by construction: the index being replaced already
guaranteed at most one active row per ``(tenant_id, adapter_id)``, so mapping
every existing row onto ``level='org', scope_id=tenant_id`` cannot collide under
the wider ``(tenant_id, adapter_id, level, scope_id)`` index. No row is dropped
and no credential is detached.

Revision ID: 0078_scoped_integration_connections
Revises: 0077_trajectory
"""

from __future__ import annotations

from alembic import op

revision = "0078_scoped_integration_connections"
down_revision = "0077_trajectory"
branch_labels = None
depends_on = None

_UP = """
-- The backfill below is an UPDATE against a FORCE-RLS table with no app.tenant_id
-- set, which a non-bypassing role would silently match zero rows for. Fail loudly
-- instead. No-op for the superuser the default compose connects as.
SET LOCAL row_security = off;

-- The org-wide gate, mirroring allow_own_ai_keys: when false, a user-scoped
-- connection is skipped entirely and only the org row is consulted, so an org
-- can forbid members bringing their own credentials without deleting theirs.
ALTER TABLE organisations
  ADD COLUMN IF NOT EXISTS allow_own_integration_credentials
      BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE integration_connections
  ADD COLUMN IF NOT EXISTS level    TEXT NOT NULL DEFAULT 'org',  -- org | user
  ADD COLUMN IF NOT EXISTS scope_id TEXT NOT NULL DEFAULT '';     -- org: tenant_id; user: user_id

-- Every pre-existing connection is an org-wide one. The sentinel default is
-- rewritten here rather than left in place: a column default cannot reference
-- another column, and a row left at '' would be invisible to a lookup keyed on
-- scope_id.
UPDATE integration_connections SET scope_id = tenant_id WHERE scope_id = '';

-- Drop-then-add so the constraint is idempotent (ADD CONSTRAINT has no
-- IF NOT EXISTS). The table already constrains `health` this way.
ALTER TABLE integration_connections
  DROP CONSTRAINT IF EXISTS integration_connections_level_check;
ALTER TABLE integration_connections
  ADD CONSTRAINT integration_connections_level_check
      CHECK (level IN ('org', 'user'));

-- The rule the whole change turns on: one active connection per adapter PER
-- SCOPE rather than per tenant.
DROP INDEX IF EXISTS integration_connections_one_active_adapter_idx;
CREATE UNIQUE INDEX IF NOT EXISTS integration_connections_one_active_scope_idx
  ON integration_connections(tenant_id, adapter_id, level, scope_id)
  WHERE health <> 'revoked';
"""

# Recreating the narrow index WILL fail if any tenant has both an org and a user
# connection active for one adapter. That is the correct behaviour: a downgrade
# must refuse rather than silently pick a winner and delete somebody's
# credential. Revoke the user-scoped connections first, then downgrade.
_DOWN = """
DROP INDEX IF EXISTS integration_connections_one_active_scope_idx;
CREATE UNIQUE INDEX IF NOT EXISTS integration_connections_one_active_adapter_idx
  ON integration_connections(tenant_id, adapter_id)
  WHERE health <> 'revoked';

ALTER TABLE integration_connections
  DROP CONSTRAINT IF EXISTS integration_connections_level_check;
ALTER TABLE integration_connections
  DROP COLUMN IF EXISTS scope_id,
  DROP COLUMN IF EXISTS level;

ALTER TABLE organisations
  DROP COLUMN IF EXISTS allow_own_integration_credentials;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
