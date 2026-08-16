"""Postgres persistence for camera bindings and root-free signed leases."""

from boltrig.models import utcnow

from .camera_rows import camera_binding_row, camera_lease_row


class CameraStorePG:
    async def upsert_camera_binding(self, binding):
        result = await self._pool.execute(
            """INSERT INTO camera_bindings
                 (tenant_id,device_id,camera_id,descriptor_fingerprint,owner_id,
                  connection_state,ptz_get_state,ptz_set_state,label,manufacturer,
                  product,transport,capabilities,evidence,updated_at)
               SELECT $1,$2,$3,$4,d.owner_id,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14
                 FROM devices d
                WHERE d.tenant_id=$1 AND d.id=$2 AND d.owner_id=$15
                  AND d.revoked_at IS NULL
               ON CONFLICT (tenant_id,device_id,camera_id) DO UPDATE SET
                 descriptor_fingerprint=EXCLUDED.descriptor_fingerprint,
                 connection_state=EXCLUDED.connection_state,
                 ptz_get_state=EXCLUDED.ptz_get_state,
                 ptz_set_state=EXCLUDED.ptz_set_state,
                 label=EXCLUDED.label,manufacturer=EXCLUDED.manufacturer,
                 product=EXCLUDED.product,transport=EXCLUDED.transport,
                 capabilities=EXCLUDED.capabilities,evidence=EXCLUDED.evidence,
                 updated_at=EXCLUDED.updated_at
               WHERE camera_bindings.owner_id=EXCLUDED.owner_id""",
            binding.tenant_id, binding.device_id, binding.camera_id,
            binding.descriptor_fingerprint, binding.connection_state,
            binding.ptz_get_state, binding.ptz_set_state,
            binding.label, binding.manufacturer, binding.product, binding.transport,
            binding.capabilities, binding.evidence, binding.updated_at or utcnow(),
            binding.owner_id,
        )
        return result.endswith("1")

    async def get_camera_binding(self, tenant_id, device_id, camera_id):
        row = await self._pool.fetchrow(
            """SELECT * FROM camera_bindings
                WHERE tenant_id=$1 AND device_id=$2 AND camera_id=$3""",
            tenant_id, device_id, camera_id,
        )
        return camera_binding_row(row)

    async def list_camera_bindings(self, tenant_id, owner_id, device_id=None):
        if device_id is None:
            rows = await self._pool.fetch(
                """SELECT * FROM camera_bindings
                    WHERE tenant_id=$1 AND owner_id=$2
                    ORDER BY camera_id,device_id""",
                tenant_id, owner_id,
            )
        else:
            rows = await self._pool.fetch(
                """SELECT * FROM camera_bindings
                    WHERE tenant_id=$1 AND owner_id=$2 AND device_id=$3
                    ORDER BY camera_id,device_id""",
                tenant_id, owner_id, device_id,
            )
        return [camera_binding_row(row) for row in rows]

    async def create_camera_lease(self, lease):
        row = await self._pool.fetchrow(
            """INSERT INTO camera_leases
                 (id,tenant_id,device_id,camera_id,owner_id,verb,action,
                  action_digest,approval_id,issued_at,expires_at,signature,
                  signing_key_id,status)
               SELECT $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,'issued'
                 FROM devices d
                 JOIN camera_bindings b
                   ON b.tenant_id=d.tenant_id AND b.device_id=d.id
                  AND b.camera_id=$4
                 JOIN hitl_requests h
                   ON h.tenant_id=d.tenant_id AND h.id=$9
                 JOIN hitl_responses hr
                   ON hr.tenant_id=h.tenant_id AND hr.request_id=h.id
                WHERE d.tenant_id=$2 AND d.id=$3 AND d.owner_id=$5
                  AND d.revoked_at IS NULL AND d.lease_verify_key_id=$13
                  AND b.owner_id=$5 AND b.connection_state='connected'
                  AND b.ptz_get_state IN ('readable','proven')
                  AND ($6 <> 'camera.ptz.set' OR b.ptz_set_state='proven')
                  AND b.descriptor_fingerprint=$7->>'descriptor_fingerprint'
                  AND h.status='consumed' AND h.type='approval'
                  AND h.verb=$6 AND h.action_digest=$8
                  AND NOT EXISTS (
                    SELECT 1 FROM camera_leases prior
                     WHERE prior.tenant_id=$2 AND prior.approval_id=$9
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM run_cancel_requests c
                     WHERE c.tenant_id=h.tenant_id AND c.run_id=h.run_id
                  )
                  AND $5 IN (h.requested_by,h.requested_on_behalf_of)
                  AND (h.timeout_at IS NULL OR h.timeout_at > now())
                  AND hr.respondent IS DISTINCT FROM h.requested_by
                  AND hr.respondent IS DISTINCT FROM h.requested_on_behalf_of
                  AND lower(btrim(hr.decision)) IN ('approve','approved','yes','allow')
                  AND $11 > now() AND $11 <= now() + interval '120 seconds'
               ON CONFLICT DO NOTHING RETURNING id""",
            lease.id, lease.tenant_id, lease.device_id, lease.camera_id,
            lease.owner_id, lease.verb, lease.action, lease.action_digest,
            lease.approval_id, lease.issued_at, lease.expires_at,
            lease.signature, lease.signing_key_id,
        )
        return row is not None

    async def get_camera_lease(self, tenant_id, device_id, lease_id):
        row = await self._pool.fetchrow(
            """SELECT * FROM camera_leases
                WHERE tenant_id=$1 AND device_id=$2 AND id=$3""",
            tenant_id, device_id, lease_id,
        )
        return camera_lease_row(row)

    async def list_pending_camera_leases(self, tenant_id, device_id, limit=50):
        bounded = max(1, min(int(limit), 50))
        rows = await self._pool.fetch(
            """SELECT l.* FROM camera_leases l
                 JOIN devices d ON d.tenant_id=l.tenant_id AND d.id=l.device_id
                 JOIN camera_bindings b ON b.tenant_id=l.tenant_id
                    AND b.device_id=l.device_id AND b.camera_id=l.camera_id
                 JOIN hitl_requests h ON h.tenant_id=l.tenant_id AND h.id=l.approval_id
                WHERE l.tenant_id=$1 AND l.device_id=$2 AND l.status='issued'
                  AND l.expires_at >= now() AND d.revoked_at IS NULL
                  AND b.connection_state='connected'
                  AND NOT EXISTS (
                    SELECT 1 FROM run_cancel_requests c
                     WHERE c.tenant_id=h.tenant_id AND c.run_id=h.run_id
                  )
                ORDER BY l.issued_at,l.id LIMIT $3""",
            tenant_id, device_id, bounded,
        )
        return [camera_lease_row(row) for row in rows]

    async def list_camera_leases_for_owner(self, tenant_id, owner_id, device_id, limit=50):
        device = await self._pool.fetchrow(
            """SELECT id FROM devices WHERE tenant_id=$1 AND id=$2 AND owner_id=$3""",
            tenant_id, device_id, owner_id,
        )
        if device is None:
            return None
        bounded = max(1, min(int(limit), 50))
        rows = await self._pool.fetch(
            """SELECT l.* FROM camera_leases l
                 JOIN devices d ON d.tenant_id=l.tenant_id AND d.id=l.device_id
                WHERE l.tenant_id=$1 AND l.device_id=$2 AND l.owner_id=$3
                  AND d.owner_id=$3
                ORDER BY l.issued_at DESC,l.id DESC LIMIT $4""",
            tenant_id, device_id, owner_id, bounded,
        )
        return [camera_lease_row(row) for row in rows]

    async def claim_camera_lease(
        self, tenant_id, device_id, lease_id, signature, claim_token_hash, claim_expires_at
    ):
        row = await self._pool.fetchrow(
            """UPDATE camera_leases l
                  SET status='claimed',claim_token_hash=$5,
                      claim_expires_at=$6,claimed_at=now()
                 FROM devices d,camera_bindings b,hitl_requests h
                WHERE l.tenant_id=$1 AND l.device_id=$2 AND l.id=$3
                  AND l.signature=$4 AND l.status='issued' AND l.expires_at >= now()
                  AND $6 > now() AND $6 <= now() + interval '5 minutes'
                  AND d.tenant_id=l.tenant_id AND d.id=l.device_id AND d.revoked_at IS NULL
                  AND b.tenant_id=l.tenant_id AND b.device_id=l.device_id
                  AND b.camera_id=l.camera_id AND b.connection_state='connected'
                  AND h.tenant_id=l.tenant_id AND h.id=l.approval_id
                RETURNING l.*""",
            tenant_id, device_id, lease_id, signature, claim_token_hash, claim_expires_at,
        )
        return camera_lease_row(row)

    async def settle_camera_lease(
        self, tenant_id, device_id, lease_id, claim_token_hash, status, receipt
    ):
        row = await self._pool.fetchrow(
            """UPDATE camera_leases
                  SET status=$5,receipt=$6,settled_at=now(),claim_token_hash=NULL
                WHERE tenant_id=$1 AND device_id=$2 AND id=$3
                  AND claim_token_hash=$4 AND status='claimed'
                  AND $5 IN ('completed','failed') AND claim_expires_at >= now()
                RETURNING id""",
            tenant_id, device_id, lease_id, claim_token_hash, status, receipt,
        )
        return row is not None
