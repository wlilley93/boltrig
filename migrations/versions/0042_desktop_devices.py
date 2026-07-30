"""Enrolled desktop devices and exact-action single-use leases.

Revision ID: 0042_desktop_devices
Revises: 0041_realtime_calls
"""

from __future__ import annotations

from alembic import op

revision = "0042_desktop_devices"
down_revision = "0041_realtime_calls"
branch_labels = None
depends_on = None

_UP = r"""
ALTER TABLE hitl_requests ADD COLUMN IF NOT EXISTS action_digest TEXT;

CREATE TABLE IF NOT EXISTS device_enrollments (
    id TEXT NOT NULL, tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL,
    label TEXT NOT NULL, authorization_code_hash TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL, consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,authorization_code_hash),
    CONSTRAINT device_enrollment_hash_sha256
      CHECK (authorization_code_hash ~ '^[0-9a-f]{64}$')
);
CREATE TABLE IF NOT EXISTS devices (
    id TEXT NOT NULL, tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL,
    label TEXT NOT NULL, public_key TEXT NOT NULL,
    public_key_fingerprint TEXT NOT NULL, lease_verify_key_id TEXT NOT NULL,
    availability_mode TEXT NOT NULL DEFAULT 'unlocked_session',
    presence TEXT NOT NULL DEFAULT 'offline',
    session_token_hash TEXT, session_expires_at TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ, revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,session_token_hash),
    CONSTRAINT device_availability_mode_valid
      CHECK (availability_mode IN ('unlocked_session')),
    CONSTRAINT device_presence_valid
      CHECK (presence IN ('offline','online','locked','revoked')),
    CONSTRAINT device_session_hash_sha256
      CHECK (session_token_hash IS NULL OR session_token_hash ~ '^[0-9a-f]{64}$')
);
CREATE INDEX IF NOT EXISTS devices_owner_idx
  ON devices(tenant_id,owner_id,created_at);
CREATE TABLE IF NOT EXISTS device_roots (
    id TEXT NOT NULL, tenant_id TEXT NOT NULL, device_id TEXT NOT NULL,
    label TEXT NOT NULL, scope TEXT NOT NULL,
    command_enabled BOOLEAN NOT NULL DEFAULT false,
    git_enabled BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), revoked_at TIMESTAMPTZ,
    PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,id,device_id),
    CONSTRAINT device_root_scope_valid CHECK (scope IN ('read','read_write')),
    FOREIGN KEY (tenant_id,device_id) REFERENCES devices(tenant_id,id)
      ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS device_roots_device_idx
  ON device_roots(tenant_id,device_id,created_at);
CREATE TABLE IF NOT EXISTS device_leases (
    id TEXT NOT NULL, tenant_id TEXT NOT NULL, device_id TEXT NOT NULL,
    root_id TEXT NOT NULL, owner_id TEXT NOT NULL, verb TEXT NOT NULL,
    action JSONB NOT NULL, action_digest TEXT NOT NULL,
    approval_id TEXT NOT NULL, issued_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL, signature TEXT NOT NULL,
    signing_key_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'issued',
    claim_token_hash TEXT, claim_expires_at TIMESTAMPTZ,
    claimed_at TIMESTAMPTZ, settled_at TIMESTAMPTZ, receipt JSONB,
    PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,approval_id),
    CONSTRAINT device_lease_verb_valid
      CHECK (verb IN ('device.file.read','device.file.write','device.command.run')),
    CONSTRAINT device_lease_status_valid
      CHECK (status IN ('issued','claimed','completed','failed','expired')),
    CONSTRAINT device_lease_action_object
      CHECK (jsonb_typeof(action) = 'object'),
    CONSTRAINT device_lease_digest_sha256
      CHECK (action_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT device_lease_claim_hash_sha256
      CHECK (claim_token_hash IS NULL OR claim_token_hash ~ '^[0-9a-f]{64}$'),
    FOREIGN KEY (tenant_id,device_id) REFERENCES devices(tenant_id,id)
      ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,root_id,device_id)
      REFERENCES device_roots(tenant_id,id,device_id)
      ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,approval_id) REFERENCES hitl_requests(tenant_id,id)
      ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS device_leases_pending_idx
  ON device_leases(tenant_id,device_id,status,issued_at);
DO $$
DECLARE t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'device_enrollments','devices','device_roots','device_leases'
  ] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON %I '
      'USING (tenant_id = current_setting(''app.tenant_id'', true)) '
      'WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))', t
    );
  END LOOP;
END
$$;
"""

_DOWN = """
DROP TABLE IF EXISTS device_leases;
DROP TABLE IF EXISTS device_roots;
DROP TABLE IF EXISTS devices;
DROP TABLE IF EXISTS device_enrollments;
ALTER TABLE hitl_requests DROP COLUMN IF EXISTS action_digest;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
