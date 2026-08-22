"""Postgres device enrollment, root and exact-action lease persistence."""

from .device_rows import device_row, lease_row, root_row


class DeviceStorePG:
    async def create_device_enrollment(self, enrollment):
        result = await self._pool.execute(
            """INSERT INTO device_enrollments
                 (id,tenant_id,owner_id,label,authorization_code_hash,
                  expires_at,created_at,consumed_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
               ON CONFLICT (tenant_id,id) DO NOTHING""",
            enrollment.id, enrollment.tenant_id, enrollment.owner_id,
            enrollment.label, enrollment.authorization_code_hash,
            enrollment.expires_at, enrollment.created_at, enrollment.consumed_at,
        )
        return result.endswith("1")

    async def complete_device_enrollment(
        self, tenant_id, enrollment_id, authorization_code_hash, device
    ):
        from .postgres import _apply_guc
        from .tenant_scope import pool_assumes_app_role

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await _apply_guc(conn, assume_role=pool_assumes_app_role(self._pool))
                row = await conn.fetchrow(
                    """UPDATE device_enrollments SET consumed_at=now()
                       WHERE tenant_id=$1 AND id=$2
                         AND authorization_code_hash=$3
                         AND consumed_at IS NULL AND expires_at >= now()
                       RETURNING owner_id,label""",
                    tenant_id, enrollment_id, authorization_code_hash,
                )
                if row is None:
                    return None
                inserted = await conn.fetchrow(
                    """INSERT INTO devices
                         (id,tenant_id,owner_id,label,public_key,
                          public_key_fingerprint,lease_verify_key_id,
                          availability_mode,presence,session_token_hash,
                          session_expires_at,created_at,updated_at)
                       VALUES
                         ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                       RETURNING *""",
                    device.id, device.tenant_id, row["owner_id"], row["label"],
                    device.public_key, device.public_key_fingerprint,
                    device.lease_verify_key_id, device.availability_mode,
                    device.presence, device.session_token_hash,
                    device.session_expires_at, device.created_at, device.updated_at,
                )
        return device_row(inserted)

    async def get_device(self, tenant_id, device_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM devices WHERE tenant_id=$1 AND id=$2",
            tenant_id, device_id,
        )
        return device_row(row)

    async def list_devices(self, tenant_id, owner_id):
        rows = await self._pool.fetch(
            """SELECT * FROM devices WHERE tenant_id=$1 AND owner_id=$2
               ORDER BY created_at,id""",
            tenant_id, owner_id,
        )
        return [device_row(row) for row in rows]

    async def list_devices_for_tenant(self, tenant_id):
        rows = await self._pool.fetch(
            """SELECT * FROM devices WHERE tenant_id=$1
               ORDER BY owner_id,created_at,id""",
            tenant_id,
        )
        return [device_row(row) for row in rows]

    async def authenticate_device_session(
        self, tenant_id, device_id, token_hash
    ):
        row = await self._pool.fetchrow(
            """UPDATE devices SET last_seen_at=now(),presence='online',
                                  updated_at=now()
               WHERE tenant_id=$1 AND id=$2 AND revoked_at IS NULL
                 AND session_token_hash=$3 AND session_expires_at >= now()
               RETURNING *""",
            tenant_id, device_id, token_hash,
        )
        return device_row(row)

    async def rotate_device_session(
        self, tenant_id, device_id, old_hash, new_hash, expires_at
    ):
        row = await self._pool.fetchrow(
            """UPDATE devices SET session_token_hash=$4,
                                  session_expires_at=$5,updated_at=now()
               WHERE tenant_id=$1 AND id=$2 AND session_token_hash=$3
                 AND session_expires_at >= now() AND revoked_at IS NULL
               RETURNING id""",
            tenant_id, device_id, old_hash, new_hash, expires_at,
        )
        return row is not None

    async def revoke_device(self, tenant_id, device_id, owner_id):
        row = await self._pool.fetchrow(
            """UPDATE devices SET revoked_at=now(),presence='revoked',
                                  session_token_hash=NULL,
                                  session_expires_at=NULL,updated_at=now()
               WHERE tenant_id=$1 AND id=$2 AND owner_id=$3
                 AND revoked_at IS NULL RETURNING id""",
            tenant_id, device_id, owner_id,
        )
        return row is not None

    async def create_device_root(self, root, owner_id):
        row = await self._pool.fetchrow(
            """INSERT INTO device_roots
                 (id,tenant_id,device_id,label,scope,command_enabled,
                  git_enabled,created_at,revoked_at)
               SELECT $1,$2,$3,$4,$5,$6,$7,$8,$9 FROM devices
                WHERE tenant_id=$2 AND id=$3 AND owner_id=$10
                  AND revoked_at IS NULL
               ON CONFLICT (tenant_id,id) DO NOTHING RETURNING id""",
            root.id, root.tenant_id, root.device_id, root.label, root.scope,
            root.command_enabled, root.git_enabled, root.created_at,
            root.revoked_at, owner_id,
        )
        return row is not None

    async def list_device_roots(self, tenant_id, device_id):
        rows = await self._pool.fetch(
            """SELECT * FROM device_roots
                WHERE tenant_id=$1 AND device_id=$2 AND revoked_at IS NULL
                ORDER BY created_at,id""",
            tenant_id, device_id,
        )
        return [root_row(row) for row in rows]

    async def revoke_device_root(
        self, tenant_id, device_id, root_id, owner_id
    ):
        row = await self._pool.fetchrow(
            """UPDATE device_roots r SET revoked_at=now()
                FROM devices d
               WHERE r.tenant_id=$1 AND r.device_id=$2 AND r.id=$3
                 AND d.tenant_id=r.tenant_id AND d.id=r.device_id
                 AND d.owner_id=$4 AND r.revoked_at IS NULL RETURNING r.id""",
            tenant_id, device_id, root_id, owner_id,
        )
        return row is not None

    async def create_device_lease(self, lease):
        command_required = lease.verb == "device.command.run"
        row = await self._pool.fetchrow(
            """INSERT INTO device_leases
                 (id,tenant_id,device_id,root_id,owner_id,verb,action,
                  action_digest,approval_id,issued_at,expires_at,signature,
                  signing_key_id,status)
               SELECT $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,'issued'
                 FROM devices d JOIN device_roots r
                   ON r.tenant_id=d.tenant_id AND r.device_id=d.id
                 JOIN hitl_requests h
                   ON h.tenant_id=d.tenant_id AND h.id=$9
                 JOIN hitl_responses hr
                   ON hr.tenant_id=h.tenant_id AND hr.request_id=h.id
                WHERE d.tenant_id=$2 AND d.id=$3 AND d.owner_id=$5
                  AND d.revoked_at IS NULL
                  AND d.lease_verify_key_id=$13 AND r.id=$4
                  AND r.revoked_at IS NULL
                  AND h.status='consumed' AND h.type='approval'
                  AND h.verb=$6 AND h.action_digest=$8
                  AND NOT EXISTS (
                    SELECT 1 FROM run_cancel_requests c
                     WHERE c.tenant_id=h.tenant_id AND c.run_id=h.run_id
                  )
                  AND $5 IN (h.requested_by,h.requested_on_behalf_of)
                  AND (h.timeout_at IS NULL OR h.timeout_at > now())
                  AND hr.respondent IS DISTINCT FROM h.requested_by
                  AND hr.respondent IS DISTINCT FROM h.requested_on_behalf_of
                  AND lower(btrim(hr.decision))
                      IN ('approve','approved','yes','allow')
                  AND ($6 <> 'device.file.write' OR r.scope='read_write')
                  AND (NOT $14 OR r.command_enabled)
                  AND $11 > now() AND $11 <= now() + interval '120 seconds'
               ON CONFLICT DO NOTHING RETURNING id""",
            lease.id, lease.tenant_id, lease.device_id, lease.root_id,
            lease.owner_id, lease.verb, lease.action, lease.action_digest,
            lease.approval_id, lease.issued_at, lease.expires_at,
            lease.signature, lease.signing_key_id, command_required,
        )
        return row is not None

    async def get_device_lease(self, tenant_id, device_id, lease_id):
        row = await self._pool.fetchrow(
            """SELECT * FROM device_leases
                WHERE tenant_id=$1 AND device_id=$2 AND id=$3""",
            tenant_id, device_id, lease_id,
        )
        return lease_row(row)

    async def list_pending_device_leases(
        self, tenant_id, device_id, limit=50
    ):
        bounded = max(1, min(int(limit), 50))
        rows = await self._pool.fetch(
            """SELECT l.* FROM device_leases l
                 JOIN devices d
                   ON d.tenant_id=l.tenant_id AND d.id=l.device_id
                 JOIN device_roots r
                   ON r.tenant_id=l.tenant_id AND r.id=l.root_id
                 JOIN hitl_requests h
                   ON h.tenant_id=l.tenant_id AND h.id=l.approval_id
                WHERE l.tenant_id=$1 AND l.device_id=$2
                  AND l.status='issued' AND l.expires_at >= now()
                  AND d.revoked_at IS NULL AND r.revoked_at IS NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM run_cancel_requests c
                     WHERE c.tenant_id=h.tenant_id AND c.run_id=h.run_id
                  )
                ORDER BY l.issued_at,l.id LIMIT $3""",
            tenant_id, device_id, bounded,
        )
        return [lease_row(row) for row in rows]

    async def list_device_leases_for_owner(
        self, tenant_id, owner_id, device_id, limit=50
    ):
        device = await self._pool.fetchrow(
            """SELECT id FROM devices
                WHERE tenant_id=$1 AND id=$2 AND owner_id=$3""",
            tenant_id, device_id, owner_id,
        )
        if device is None:
            return None
        bounded = max(1, min(int(limit), 50))
        rows = await self._pool.fetch(
            """SELECT l.* FROM device_leases l
                 JOIN devices d
                   ON d.tenant_id=l.tenant_id AND d.id=l.device_id
                WHERE l.tenant_id=$1 AND l.device_id=$2
                  AND l.owner_id=$3 AND d.owner_id=$3
                ORDER BY l.issued_at DESC,l.id DESC LIMIT $4""",
            tenant_id, device_id, owner_id, bounded,
        )
        return [lease_row(row) for row in rows]

    async def claim_device_lease(
        self, tenant_id, device_id, lease_id, signature,
        claim_token_hash, claim_expires_at,
    ):
        row = await self._pool.fetchrow(
            """UPDATE device_leases l
                  SET status='claimed',claim_token_hash=$5,
                      claim_expires_at=$6,claimed_at=now()
                 FROM devices d,device_roots r,hitl_requests h
                WHERE l.tenant_id=$1 AND l.device_id=$2 AND l.id=$3
                  AND l.signature=$4 AND l.status='issued'
                  AND l.expires_at >= now()
                  AND $6 > now() AND $6 <= now() + interval '5 minutes'
                  AND d.tenant_id=l.tenant_id AND d.id=l.device_id
                  AND d.revoked_at IS NULL
                  AND r.tenant_id=l.tenant_id AND r.id=l.root_id
                  AND r.revoked_at IS NULL
                  AND h.tenant_id=l.tenant_id AND h.id=l.approval_id
                  AND NOT EXISTS (
                    SELECT 1 FROM run_cancel_requests c
                     WHERE c.tenant_id=h.tenant_id AND c.run_id=h.run_id
                  )
                RETURNING l.*""",
            tenant_id, device_id, lease_id, signature,
            claim_token_hash, claim_expires_at,
        )
        return lease_row(row)

    async def settle_device_lease(
        self, tenant_id, device_id, lease_id, claim_token_hash, status, receipt
    ):
        row = await self._pool.fetchrow(
            """UPDATE device_leases
                  SET status=$5,receipt=$6,settled_at=now(),
                      claim_token_hash=NULL
                WHERE tenant_id=$1 AND device_id=$2 AND id=$3
                  AND claim_token_hash=$4 AND status='claimed'
                  AND $5 IN ('completed','failed')
                  AND claim_expires_at >= now() RETURNING id""",
            tenant_id, device_id, lease_id, claim_token_hash, status, receipt,
        )
        return row is not None
