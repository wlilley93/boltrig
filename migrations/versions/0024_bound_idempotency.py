"""Bind idempotency claims to identity/request and make side effects single-owner.

Existing cached outputs are deliberately invalidated.  They predate identity and
request binding, so replaying them after this upgrade would preserve the confused-
deputy weakness this revision closes.

Revision ID: 0024_bound_idempotency
Revises: 0023_hitl_request_binding
"""

from __future__ import annotations

from alembic import op

revision = "0024_bound_idempotency"
down_revision = "0023_hitl_request_binding"
branch_labels = None
depends_on = None

_DDL = r"""
ALTER TABLE verbs
    ADD COLUMN IF NOT EXISTS idempotency_mode TEXT NOT NULL DEFAULT 'cacheable';

-- Old rows are not safely attributable to an actor/request.  Empty the replay
-- cache while preserving the table and any FORCE-RLS policy already applied.
TRUNCATE TABLE idempotency_keys;
ALTER TABLE idempotency_keys ADD COLUMN IF NOT EXISTS actor TEXT;
ALTER TABLE idempotency_keys ADD COLUMN IF NOT EXISTS on_behalf_of TEXT;
ALTER TABLE idempotency_keys ADD COLUMN IF NOT EXISTS workspace_id TEXT;
ALTER TABLE idempotency_keys ADD COLUMN IF NOT EXISTS noun TEXT;
ALTER TABLE idempotency_keys ADD COLUMN IF NOT EXISTS verb TEXT;
ALTER TABLE idempotency_keys ADD COLUMN IF NOT EXISTS request_hash TEXT;
ALTER TABLE idempotency_keys ADD COLUMN IF NOT EXISTS status TEXT;
ALTER TABLE idempotency_keys ADD COLUMN IF NOT EXISTS owner_token TEXT;
ALTER TABLE idempotency_keys ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ;
ALTER TABLE idempotency_keys ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();
ALTER TABLE idempotency_keys ALTER COLUMN actor SET NOT NULL;
ALTER TABLE idempotency_keys ALTER COLUMN noun SET NOT NULL;
ALTER TABLE idempotency_keys ALTER COLUMN verb SET NOT NULL;
ALTER TABLE idempotency_keys ALTER COLUMN request_hash SET NOT NULL;
ALTER TABLE idempotency_keys ALTER COLUMN status SET NOT NULL;
ALTER TABLE idempotency_keys ALTER COLUMN updated_at SET NOT NULL;

DO $migration$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'idempotency_keys'::regclass
           AND conname = 'idempotency_keys_status_check'
    ) THEN
        ALTER TABLE idempotency_keys
            ADD CONSTRAINT idempotency_keys_status_check CHECK (
                status IN ('claimed', 'executing', 'completed', 'uncertain', 'uncacheable')
            );
    END IF;
END
$migration$;

-- A one-time invitation secret cannot be replay-cached.  Make a retry fail as a
-- conflict instead of minting a second pending invitation for the same address.
WITH ranked AS (
    SELECT tenant_id, id,
           row_number() OVER (
               PARTITION BY tenant_id, lower(email)
               ORDER BY created_at DESC, id DESC
           ) AS ordinal
      FROM user_invitations
     WHERE status = 'pending'
)
UPDATE user_invitations AS invitation
   SET status = 'revoked'
  FROM ranked
 WHERE invitation.tenant_id = ranked.tenant_id
   AND invitation.id = ranked.id
   AND ranked.ordinal > 1;

CREATE UNIQUE INDEX IF NOT EXISTS invitations_one_pending_email_idx
    ON user_invitations (tenant_id, lower(email)) WHERE status = 'pending';
"""


def upgrade() -> None:
    op.execute(_DDL)


def downgrade() -> None:
    raise NotImplementedError(
        "0024 invalidates unsafe replay rows; restoring unbound cache data is unsafe"
    )
