"""HITL store domain (arc-1 structural partial).

The human-in-the-loop store methods extracted from ``store/postgres.py`` +
``store/memory.py`` to bring both under the structural floor.
``PostgresStore`` mixes in :class:`HitlStorePG`; ``InMemoryStore`` mixes in
:class:`HitlStoreMem`. The public method surface (the Store Protocol in
``base.py``) is unchanged - this is a pure structural relocation, behaviour-
and symmetry-preserving.

Host-class contract:
  - ``HitlStorePG`` uses ``self._pool`` (an asyncpg pool, set by PostgresStore).
  - ``HitlStoreMem`` uses ``self._hitl`` / ``self._hitl_resp`` (dicts,
    initialised by InMemoryStore._init_execution_state).
"""

from __future__ import annotations

from boltrig.models import HITLRequest, HITLResponse, HITLStatus

from .rls_pool import _apply_guc
from .rows import _hitl_req, _hitl_resp
from .tenant_scope import pool_assumes_app_role


class HitlStorePG:
    """HITL methods for ``PostgresStore`` (uses ``self._pool``)."""

    async def create_hitl_request(self, r: HITLRequest):
        await self._pool.execute(
            """INSERT INTO hitl_requests (id, tenant_id, run_id, work_item_id, type, urgency,
                                          context, question, options, assignee, status, timeout_at,
                                          verb, requested_by, requested_on_behalf_of, request_fingerprint, action_digest, workspace_id, department_scope,
                                          secure, secure_purpose)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 status=EXCLUDED.status, updated_at=now()""",
            r.id, r.tenant_id, r.run_id, r.work_item_id, r.type.value, r.urgency.value,
            r.context, r.question, r.options, r.assignee, r.status.value, r.timeout_at,
            r.verb, r.requested_by, r.requested_on_behalf_of, r.request_fingerprint, r.action_digest, r.workspace_id, r.department_scope,
            r.secure, r.secure_purpose,
        )

    async def consume_hitl(self, tenant_id, request_id):
        # atomic ANSWERED -> CONSUMED; RETURNING tells us if we won the CAS.
        row = await self._pool.fetchrow(
            """UPDATE hitl_requests SET status='consumed', updated_at=now()
               WHERE tenant_id=$1 AND id=$2 AND status='answered' RETURNING id""",
            tenant_id, request_id,
        )
        return row is not None

    async def expire_hitl(self, tenant_id, request_id):
        # atomic PENDING -> TIMED_OUT (SEC-14); RETURNING tells us if we won the
        # CAS, so a concurrently answered request is never clobbered.
        row = await self._pool.fetchrow(
            """UPDATE hitl_requests SET status='timed_out', updated_at=now()
               WHERE tenant_id=$1 AND id=$2 AND status='pending' RETURNING id""",
            tenant_id, request_id,
        )
        return row is not None

    async def get_hitl_request(self, tenant_id, req_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM hitl_requests WHERE tenant_id=$1 AND id=$2", tenant_id, req_id
        )
        return _hitl_req(row)

    async def list_pending_hitl(self, tenant_id):
        rows = await self._pool.fetch(
            "SELECT * FROM hitl_requests WHERE tenant_id=$1 AND status=$2",
            tenant_id, HITLStatus.PENDING.value,
        )
        return [_hitl_req(r) for r in rows]

    async def list_answered_hitl(self, tenant_id):
        rows = await self._pool.fetch(
            "SELECT * FROM hitl_requests WHERE tenant_id=$1 AND status=$2",
            tenant_id, HITLStatus.ANSWERED.value,
        )
        return [_hitl_req(r) for r in rows]

    async def list_hitl_requests_for_requester(
        self, tenant_id, requested_by, statuses, *, limit=20
    ):
        values = [
            status.value if isinstance(status, HITLStatus) else str(status)
            for status in statuses
        ]
        rows = await self._pool.fetch(
            """SELECT * FROM hitl_requests
               WHERE tenant_id=$1 AND requested_by=$2 AND status=ANY($3::text[])
               ORDER BY updated_at DESC,id
               LIMIT $4""",
            tenant_id,
            requested_by,
            values,
            max(0, min(int(limit), 100)),
        )
        return [_hitl_req(row) for row in rows]

    async def answer_hitl(self, resp: HITLResponse):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await _apply_guc(conn, assume_role=pool_assumes_app_role(self._pool))  # RLS-live: scope this explicit transaction
                row = await conn.fetchrow(
                    """UPDATE hitl_requests SET status=$3, updated_at=now()
                       WHERE tenant_id=$1 AND id=$2 AND status=$4 RETURNING *""",
                    resp.tenant_id, resp.request_id, HITLStatus.ANSWERED.value,
                    HITLStatus.PENDING.value,
                )
                if row is None:
                    return None
                await conn.execute(
                    """INSERT INTO hitl_responses (id, request_id, tenant_id, decision, notes,
                                                   respondent, responded_at)
                       VALUES ($1,$2,$3,$4,$5,$6,$7)
                       ON CONFLICT (tenant_id, id) DO NOTHING""",
                    resp.id, resp.request_id, resp.tenant_id, resp.decision, resp.notes,
                    resp.respondent, resp.responded_at,
                )
        return _hitl_req(row)

    async def get_hitl_response(self, tenant_id, request_id):
        row = await self._pool.fetchrow(
            """SELECT * FROM hitl_responses WHERE tenant_id=$1 AND request_id=$2
               ORDER BY responded_at DESC LIMIT 1""",
            tenant_id, request_id,
        )
        return _hitl_resp(row)


class HitlStoreMem:
    """HITL methods for ``InMemoryStore`` (uses ``self._hitl`` / ``self._hitl_resp``)."""

    async def create_hitl_request(self, req):
        # PG is ON CONFLICT (tenant_id, id) DO UPDATE SET status: a conflicting
        # id keeps the original row and only adopts the new status.
        key = (req.tenant_id, req.id)
        existing = self._hitl.get(key)
        if existing is not None:
            existing.status = req.status
        else:
            self._hitl[key] = req

    async def get_hitl_request(self, tenant_id, req_id):
        return self._hitl.get((tenant_id, req_id))

    async def list_pending_hitl(self, tenant_id):
        pending = HITLStatus.PENDING
        return [r for (t, _), r in self._hitl.items() if t == tenant_id and r.status == pending]

    async def list_answered_hitl(self, tenant_id):
        answered = HITLStatus.ANSWERED
        return [r for (t, _), r in self._hitl.items() if t == tenant_id and r.status == answered]

    async def list_hitl_requests_for_requester(
        self, tenant_id, requested_by, statuses, *, limit=20
    ):
        allowed = {
            status.value if isinstance(status, HITLStatus) else str(status) for status in statuses
        }
        rows = [
            request
            for (tenant, _), request in self._hitl.items()
            if tenant == tenant_id
            and request.requested_by == requested_by
            and request.status.value in allowed
        ]
        bounded = max(0, min(int(limit), 100))
        return rows[-bounded:] if bounded else []

    async def answer_hitl(self, resp):
        req = self._hitl.get((resp.tenant_id, resp.request_id))
        if req is None or req.status != HITLStatus.PENDING:
            return None
        self._hitl_resp[(resp.tenant_id, resp.id)] = resp
        req.status = HITLStatus.ANSWERED
        return req

    async def get_hitl_response(self, tenant_id, request_id):
        matches = [
            resp
            for resp in self._hitl_resp.values()
            if resp.tenant_id == tenant_id and resp.request_id == request_id
        ]
        # Newest first, matching the PG ORDER BY responded_at DESC LIMIT 1.
        return max(matches, key=lambda r: r.responded_at, default=None)

    async def consume_hitl(self, tenant_id, request_id):
        # atomic ANSWERED -> CONSUMED (single-use). No await between the check and
        # the write, so it is atomic under cooperative scheduling.
        req = self._hitl.get((tenant_id, request_id))
        if req is None or req.status != HITLStatus.ANSWERED:
            return False
        req.status = HITLStatus.CONSUMED
        return True

    async def expire_hitl(self, tenant_id, request_id):
        # atomic PENDING -> TIMED_OUT (SEC-14). Same no-await CAS shape as
        # consume_hitl: a concurrently answered request is never clobbered.
        req = self._hitl.get((tenant_id, request_id))
        if req is None or req.status != HITLStatus.PENDING:
            return False
        req.status = HITLStatus.TIMED_OUT
        return True
