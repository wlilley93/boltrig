"""Durable generic UVC camera bindings and root-free semantic leases."""

from __future__ import annotations

from alembic import op

revision = "0068_camera_uvc_leases"
down_revision = "0067_background_job_reflection"
branch_labels = None
depends_on = None

_UP = r"""
CREATE TABLE IF NOT EXISTS camera_bindings (
    tenant_id TEXT NOT NULL, device_id TEXT NOT NULL, camera_id TEXT NOT NULL,
    descriptor_fingerprint TEXT NOT NULL, owner_id TEXT NOT NULL,
    connection_state TEXT NOT NULL, ptz_get_state TEXT NOT NULL,
    ptz_set_state TEXT NOT NULL, label TEXT NOT NULL DEFAULT '',
    manufacturer TEXT, product TEXT, transport TEXT NOT NULL DEFAULT 'uvc_libusb',
    capabilities JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id,device_id,camera_id),
    CONSTRAINT camera_binding_fingerprint_sha256
      CHECK (descriptor_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT camera_binding_connection_valid
      CHECK (connection_state IN ('connected','disconnected','permission_required','unknown')),
    CONSTRAINT camera_binding_get_state_valid
      CHECK (ptz_get_state IN ('unknown','advertised','readable','writable','proven','unsupported','invalid_descriptor')),
    CONSTRAINT camera_binding_set_state_valid
      CHECK (ptz_set_state IN ('unknown','advertised','readable','writable','proven','unsupported','invalid_descriptor')),
    CONSTRAINT camera_binding_capabilities_object
      CHECK (jsonb_typeof(capabilities)='object'),
    CONSTRAINT camera_binding_evidence_array
      CHECK (jsonb_typeof(evidence)='array'),
    FOREIGN KEY (tenant_id,device_id) REFERENCES devices(tenant_id,id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS camera_bindings_owner_idx
  ON camera_bindings(tenant_id,owner_id,device_id,camera_id);

CREATE TABLE IF NOT EXISTS camera_leases (
    id TEXT NOT NULL, tenant_id TEXT NOT NULL, device_id TEXT NOT NULL,
    camera_id TEXT NOT NULL, owner_id TEXT NOT NULL, verb TEXT NOT NULL,
    action JSONB NOT NULL, action_digest TEXT NOT NULL, approval_id TEXT NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL, expires_at TIMESTAMPTZ NOT NULL,
    signature TEXT NOT NULL, signing_key_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'issued', claim_token_hash TEXT,
    claim_expires_at TIMESTAMPTZ, claimed_at TIMESTAMPTZ,
    settled_at TIMESTAMPTZ, receipt JSONB,
    PRIMARY KEY (tenant_id,id), UNIQUE (tenant_id,approval_id),
    CONSTRAINT camera_lease_verb_valid
      CHECK (verb IN ('camera.ptz.get','camera.ptz.set')),
    CONSTRAINT camera_lease_status_valid
      CHECK (status IN ('issued','claimed','completed','failed','expired')),
    CONSTRAINT camera_lease_action_object
      CHECK (jsonb_typeof(action)='object'),
    CONSTRAINT camera_lease_digest_sha256
      CHECK (action_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT camera_lease_claim_hash_sha256
      CHECK (claim_token_hash IS NULL OR claim_token_hash ~ '^[0-9a-f]{64}$'),
    FOREIGN KEY (tenant_id,device_id,camera_id)
      REFERENCES camera_bindings(tenant_id,device_id,camera_id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id,approval_id)
      REFERENCES hitl_requests(tenant_id,id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS camera_leases_pending_idx
  ON camera_leases(tenant_id,device_id,status,issued_at);
DO $$
DECLARE t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY['camera_bindings','camera_leases'] LOOP
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
DROP TABLE IF EXISTS camera_leases;
DROP TABLE IF EXISTS camera_bindings;
"""


def upgrade() -> None:
    op.execute(_UP)


def downgrade() -> None:
    op.execute(_DOWN)
