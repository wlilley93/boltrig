"""org/workspace-scoped invites + provisioning ([2026] VJS-COUNTY 8, D6).

An ordered delta bringing an existing database up to carry the org/workspace scope
and provisioning intent on invitations. The change is idempotent (ADD COLUMN IF
NOT EXISTS) and mirrored in the bootstrap schema. This revision also widens
Alembic's own version column before recording this 35-character revision id.

ADDITIVE + backward-compatible: the three new user_invitations columns are NULLABLE
and every existing row is left NULL, so a legacy invite (no workspace scope, no
provisioning) behaves EXACTLY as before. ``workspace_id`` targets an EXISTING
workspace the invitee is seated into on accept; ``provision_workspace_name`` asks
accept to CREATE that workspace and seat the invitee as owner; ``provision_org_name``
(superadmin-only at invite creation) asks accept to provision a brand-new org owned
by the invitee. These are application-level fields consumed by accept-invite, not
RLS predicates: RLS stays tenant_id-fenced on user_invitations exactly as before.

Revision ID: 0015_invitation_workspace_provision
Revises: 0014_workflow_workspace_scope
"""

from __future__ import annotations

from alembic import op

revision = "0015_invitation_workspace_provision"
down_revision = "0014_workflow_workspace_scope"
branch_labels = None
depends_on = None

_DDL = """
-- Alembic creates version_num as VARCHAR(32). This revision id is 35 characters,
-- so widen the metadata column before Alembic writes the new head after upgrade().
-- Keep the wider type on downgrade: later revision ids may also need it.
ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64);
ALTER TABLE user_invitations ADD COLUMN IF NOT EXISTS workspace_id TEXT;
ALTER TABLE user_invitations ADD COLUMN IF NOT EXISTS provision_workspace_name TEXT;
ALTER TABLE user_invitations ADD COLUMN IF NOT EXISTS provision_org_name TEXT;
"""

_DOWN = """
ALTER TABLE user_invitations DROP COLUMN IF EXISTS provision_org_name;
ALTER TABLE user_invitations DROP COLUMN IF EXISTS provision_workspace_name;
ALTER TABLE user_invitations DROP COLUMN IF EXISTS workspace_id;
"""


def upgrade() -> None:
    op.execute(_DDL)


def downgrade() -> None:
    op.execute(_DOWN)
