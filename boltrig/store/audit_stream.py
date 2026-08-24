"""Audit-stream store domain (arc-1 structural partial).

The tamper-evident audit chain, security event stream and audit rollup anchors
extracted from ``store/postgres.py`` + ``store/memory.py`` to bring both under
the structural floor. ``PostgresStore`` mixes in :class:`AuditStreamStorePG`;
``InMemoryStore`` mixes in :class:`AuditStreamStoreMem`. The public method
surface (the Store Protocol in ``base.py``) is unchanged - pure structural
relocation, behaviour- and symmetry-preserving.

Host-class contract:
  - ``AuditStreamStorePG`` uses ``self._pool`` (an asyncpg pool).
  - ``AuditStreamStoreMem`` uses ``self._audit`` / ``self._security`` /
    ``self._anchors`` (tenant-keyed lists, initialised by
    InMemoryStore._init_execution_state) and a lazily-created ``_audit_outbox``
    list.
"""

from __future__ import annotations

import json

from boltrig.models import (
    AuditEvent,
    AuditRollupAnchor,
    SecurityEvent,
    utcnow,
)

from .rows import _anchor, _audit, _security


class AuditStreamStorePG:
    """Audit chain + security stream + rollup anchors for ``PostgresStore``."""

    async def audit_head(self, tenant_id):
        row = await self._pool.fetchrow(
            "SELECT seq, hash FROM audit_log WHERE tenant_id=$1 ORDER BY seq DESC LIMIT 1",
            tenant_id,
        )
        if row is None:
            return (0, None)
        return (row["seq"], row["hash"])

    async def audit_append(self, e: AuditEvent):
        await self._pool.execute(
            """INSERT INTO audit_log (tenant_id, seq, ts, run_id, parent_run_id, actor, actor_tier,
                                      depth, action_type, noun, verb, target_adapter, on_behalf_of,
                                      status, latency_ms, tokens_used, cost_micros, skills_loaded,
                                      detail, ip_address, user_agent, resource, resource_id,
                                      workspace_id, prev_hash, hash)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,
                       $22,$23,$24,$25,$26)""",
            e.tenant_id, e.seq, e.ts, e.run_id, e.parent_run_id, e.actor, e.actor_tier, e.depth,
            e.action_type.value, e.noun, e.verb, e.target_adapter, e.on_behalf_of, e.status,
            e.latency_ms, e.tokens_used, e.cost_micros, e.skills_loaded, e.detail,
            e.ip_address, e.user_agent, e.resource, e.resource_id, e.workspace_id,
            e.prev_hash, e.hash,
        )

    async def audit_outbox_enqueue(self, tenant_id, payload, append_error):
        # Rides the same tenant-scoped connection the faulted append was using
        # (the dispatch path binds the tenant before invoke), so the deferred
        # row lands inside the caller's own RLS fence.
        await self._pool.execute(
            """INSERT INTO audit_outbox (tenant_id, payload, append_error)
               VALUES ($1, $2::jsonb, $3)""",
            tenant_id, json.dumps(payload), append_error,
        )

    async def audit_outbox_due(self, tenant_id, now, limit=100):
        rows = await self._pool.fetch(
            """SELECT * FROM audit_outbox
                WHERE tenant_id=$1 AND next_retry_at <= $2
                ORDER BY id LIMIT $3""",
            tenant_id, now, limit,
        )
        # JSONB arrives as a str through this pool: decode to the dict the
        # memory twin returns, so the drain side is backend-agnostic.
        return [
            {**dict(row), "payload": json.loads(row["payload"])}
            if isinstance(row["payload"], str) else dict(row)
            for row in rows
        ]

    async def audit_outbox_delete(self, outbox_id):
        await self._pool.execute("DELETE FROM audit_outbox WHERE id=$1", outbox_id)

    async def audit_outbox_mark_failed(self, outbox_id, append_error, next_retry_at):
        await self._pool.execute(
            """UPDATE audit_outbox
                  SET attempts = attempts + 1, append_error=$2, next_retry_at=$3
                WHERE id=$1""",
            outbox_id, append_error, next_retry_at,
        )

    async def audit_query(self, tenant_id, run_id=None, limit=200):
        if run_id is None:
            rows = await self._pool.fetch(
                "SELECT * FROM audit_log WHERE tenant_id=$1 ORDER BY seq DESC LIMIT $2",
                tenant_id, limit,
            )
        else:
            rows = await self._pool.fetch(
                """SELECT * FROM audit_log WHERE tenant_id=$1 AND (run_id=$2 OR parent_run_id=$2)
                   ORDER BY seq DESC LIMIT $3""",
                tenant_id, run_id, limit,
            )
        return [_audit(r) for r in reversed(rows)]  # ascending, like InMemoryStore

    async def audit_scan(self, tenant_id, after_seq, limit):
        q = "SELECT * FROM audit_log WHERE tenant_id=$1 AND seq>$2 ORDER BY seq LIMIT $3"
        return [_audit(r) for r in await self._pool.fetch(q, tenant_id, after_seq, limit)]

    async def security_head(self, tenant_id):
        row = await self._pool.fetchrow(
            "SELECT seq, hash FROM security_log WHERE tenant_id=$1 ORDER BY seq DESC LIMIT 1",
            tenant_id,
        )
        if row is None:
            return (0, None)
        return (row["seq"], row["hash"])

    async def security_append(self, e: SecurityEvent):
        await self._pool.execute(
            """INSERT INTO security_log (tenant_id, seq, ts, event_type, reason, actor, actor_tier,
                                         workspace_id, ip_address, user_agent, resource, resource_id,
                                         on_behalf_of, detail, prev_hash, hash)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)""",
            e.tenant_id, e.seq, e.ts, e.event_type.value, e.reason, e.actor, e.actor_tier,
            e.workspace_id, e.ip_address, e.user_agent, e.resource, e.resource_id,
            e.on_behalf_of, e.detail, e.prev_hash, e.hash,
        )

    async def security_query(self, tenant_id, event_type=None, limit=200):
        if event_type is None:
            rows = await self._pool.fetch(
                "SELECT * FROM security_log WHERE tenant_id=$1 ORDER BY seq DESC LIMIT $2",
                tenant_id, limit,
            )
        else:
            rows = await self._pool.fetch(
                """SELECT * FROM security_log WHERE tenant_id=$1 AND event_type=$2
                   ORDER BY seq DESC LIMIT $3""",
                tenant_id, event_type, limit,
            )
        return [_security(r) for r in reversed(rows)]  # ascending, like InMemoryStore

    async def security_scan(self, tenant_id, after_seq, limit):
        q = "SELECT * FROM security_log WHERE tenant_id=$1 AND seq>$2 ORDER BY seq LIMIT $3"
        return [_security(r) for r in await self._pool.fetch(q, tenant_id, after_seq, limit)]

    async def add_audit_anchor(self, a: AuditRollupAnchor):
        await self._pool.execute(
            """INSERT INTO audit_rollup_anchors (id, tenant_id, workspace_id, seq_start, seq_end,
                                                 rollup_root_hash, anchored_at, is_dev_fallback,
                                                 rfc3161_token, kms_signature)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)""",
            a.id, a.tenant_id, a.workspace_id, a.seq_start, a.seq_end, a.rollup_root_hash,
            a.anchored_at, a.is_dev_fallback, a.rfc3161_token, a.kms_signature,
        )

    async def latest_audit_anchor(self, tenant_id, workspace_id=None):
        # workspace_id NULL selects the ORG-WIDE anchor stream (IS NULL), not "any".
        row = await self._pool.fetchrow(
            """SELECT * FROM audit_rollup_anchors
               WHERE tenant_id=$1 AND workspace_id IS NOT DISTINCT FROM $2
               ORDER BY seq_end DESC LIMIT 1""",
            tenant_id, workspace_id,
        )
        return _anchor(row)

    async def list_audit_anchors(self, tenant_id, workspace_id=None, limit=200):
        if workspace_id is None:
            rows = await self._pool.fetch(
                """SELECT * FROM audit_rollup_anchors WHERE tenant_id=$1
                   ORDER BY seq_end DESC LIMIT $2""",
                tenant_id, limit,
            )
        else:
            rows = await self._pool.fetch(
                """SELECT * FROM audit_rollup_anchors
                   WHERE tenant_id=$1 AND workspace_id=$2 ORDER BY seq_end DESC LIMIT $3""",
                tenant_id, workspace_id, limit,
            )
        return [_anchor(r) for r in reversed(rows)]  # ascending, like InMemoryStore


class AuditStreamStoreMem:
    """Audit chain + security stream + rollup anchors for ``InMemoryStore``."""

    async def audit_head(self, tenant_id):
        chain = self._audit.get(tenant_id, [])
        if not chain:
            return (0, None)
        last = chain[-1]
        return (last.seq or 0, last.hash)

    async def audit_outbox_enqueue(self, tenant_id, payload, append_error):
        if not hasattr(self, "_audit_outbox"):
            self._audit_outbox: list[dict] = []
        self._audit_outbox.append(
            {
                "id": len(self._audit_outbox) + 1,
                "tenant_id": tenant_id,
                "payload": payload,
                "append_error": append_error,
                "attempts": 0,
                "next_retry_at": utcnow(),
                "created_at": utcnow(),
            }
        )

    async def audit_outbox_due(self, tenant_id, now, limit=100):
        rows = [
            r
            for r in getattr(self, "_audit_outbox", [])
            if r["next_retry_at"] <= now and r["tenant_id"] == tenant_id
        ]
        return rows[:limit]

    async def audit_outbox_delete(self, outbox_id):
        self._audit_outbox = [r for r in getattr(self, "_audit_outbox", []) if r["id"] != outbox_id]

    async def audit_outbox_mark_failed(self, outbox_id, append_error, next_retry_at):
        for r in getattr(self, "_audit_outbox", []):
            if r["id"] == outbox_id:
                r["attempts"] += 1
                r["append_error"] = append_error
                r["next_retry_at"] = next_retry_at
                return

    async def audit_append(self, event):
        self._audit.setdefault(event.tenant_id, []).append(event)

    async def audit_query(self, tenant_id, run_id=None, limit=200):
        chain = list(self._audit.get(tenant_id, []))
        if run_id is not None:
            chain = [e for e in chain if e.run_id == run_id or e.parent_run_id == run_id]
        return chain[-limit:]

    async def audit_scan(self, tenant_id, after_seq, limit):
        return [e for e in self._audit.get(tenant_id, []) if (e.seq or 0) > after_seq][:limit]

    async def security_head(self, tenant_id):
        chain = self._security.get(tenant_id, [])
        if not chain:
            return (0, None)
        last = chain[-1]
        return (last.seq or 0, last.hash)

    async def security_append(self, event):
        self._security.setdefault(event.tenant_id, []).append(event)

    async def security_query(self, tenant_id, event_type=None, limit=200):
        chain = list(self._security.get(tenant_id, []))
        if event_type is not None:
            chain = [e for e in chain if e.event_type.value == event_type]
        return chain[-limit:]

    async def security_scan(self, tenant_id, after_seq, limit):
        return [e for e in self._security.get(tenant_id, []) if (e.seq or 0) > after_seq][:limit]

    async def add_audit_anchor(self, anchor):
        self._anchors.setdefault(anchor.tenant_id, []).append(anchor)

    async def latest_audit_anchor(self, tenant_id, workspace_id=None):
        rows = [a for a in self._anchors.get(tenant_id, []) if a.workspace_id == workspace_id]
        return rows[-1] if rows else None

    async def list_audit_anchors(self, tenant_id, workspace_id=None, limit=200):
        rows = [
            a
            for a in self._anchors.get(tenant_id, [])
            if workspace_id is None or a.workspace_id == workspace_id
        ]
        return rows[-limit:]
