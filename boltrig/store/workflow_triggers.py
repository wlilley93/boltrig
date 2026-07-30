"""Memory/PostgreSQL persistence for governed workflow trigger bindings."""

from __future__ import annotations

from dataclasses import replace
from threading import Lock

from boltrig.models import GrantSet, utcnow
from boltrig.models.workflow_triggers import (
    WorkflowTrigger,
    WorkflowTriggerDelivery,
)


def _trigger(row):
    if row is None:
        return None
    return WorkflowTrigger(
        id=row["id"],
        tenant_id=row["tenant_id"],
        workflow_id=row["workflow_id"],
        name=row["name"],
        source=row["source"],
        owner_id=row["owner_id"],
        workspace_id=row["workspace_id"],
        grant_ceiling=GrantSet.of(
            list(row["grant_allow"] or []), list(row["grant_deny"] or [])
        ),
        channel_id=row["channel_id"],
        secret_hash=row["secret_hash"],
        enabled=bool(row["enabled"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _delivery(row):
    if row is None:
        return None
    return WorkflowTriggerDelivery(
        trigger_id=row["trigger_id"],
        tenant_id=row["tenant_id"],
        source_event_digest=row["source_event_digest"],
        status=row["status"],
        authority_subject=row["authority_subject"],
        run_id=row["run_id"],
        hitl_request_id=row["hitl_request_id"],
        reason=row["reason"],
        created_at=row["created_at"],
    )


class WorkflowTriggerStorePG:
    async def create_workflow_trigger(self, trigger):
        row = await self._pool.fetchrow(
            """INSERT INTO workflow_triggers
                 (id, tenant_id, workflow_id, workspace_id, name, source,
                  owner_id, grant_allow, grant_deny, channel_id, secret_hash,
                  enabled, created_at, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,
                       COALESCE($13,now()),COALESCE($14,now()))
               ON CONFLICT (tenant_id,id) DO NOTHING
               RETURNING id""",
            trigger.id,
            trigger.tenant_id,
            trigger.workflow_id,
            trigger.workspace_id,
            trigger.name,
            trigger.source,
            trigger.owner_id,
            list(trigger.grant_ceiling.allow),
            list(trigger.grant_ceiling.deny),
            trigger.channel_id,
            trigger.secret_hash,
            trigger.enabled,
            trigger.created_at,
            trigger.updated_at,
        )
        return row is not None

    async def get_workflow_trigger(self, tenant_id, trigger_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM workflow_triggers WHERE tenant_id=$1 AND id=$2",
            tenant_id,
            trigger_id,
        )
        return _trigger(row)

    async def list_workflow_triggers(self, tenant_id, workflow_id):
        rows = await self._pool.fetch(
            """SELECT * FROM workflow_triggers
               WHERE tenant_id=$1 AND workflow_id=$2
               ORDER BY created_at,id""",
            tenant_id,
            workflow_id,
        )
        return [_trigger(row) for row in rows]

    async def list_channel_workflow_triggers(
        self, tenant_id, channel_id, *, limit=32
    ):
        rows = await self._pool.fetch(
            """SELECT * FROM workflow_triggers
               WHERE tenant_id=$1 AND channel_id=$2
                 AND source='channel' AND enabled=true
               ORDER BY created_at,id LIMIT $3""",
            tenant_id,
            channel_id,
            max(0, min(limit, 32)),
        )
        return [_trigger(row) for row in rows]

    async def set_workflow_trigger_enabled(
        self, tenant_id, trigger_id, enabled
    ):
        row = await self._pool.fetchrow(
            """UPDATE workflow_triggers
                  SET enabled=$3,updated_at=now()
                WHERE tenant_id=$1 AND id=$2 RETURNING *""",
            tenant_id,
            trigger_id,
            bool(enabled),
        )
        return _trigger(row)

    async def rotate_workflow_trigger_secret(
        self, tenant_id, trigger_id, secret_hash
    ):
        row = await self._pool.fetchrow(
            """UPDATE workflow_triggers
                  SET secret_hash=$3,updated_at=now()
                WHERE tenant_id=$1 AND id=$2 AND source='webhook'
                RETURNING *""",
            tenant_id,
            trigger_id,
            secret_hash,
        )
        return _trigger(row)

    async def record_workflow_trigger_delivery(self, delivery):
        row = await self._pool.fetchrow(
            """INSERT INTO workflow_trigger_deliveries
                 (tenant_id,trigger_id,source_event_digest,status,
                  authority_subject,run_id,hitl_request_id,reason,created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,COALESCE($9,now()))
               ON CONFLICT (tenant_id,trigger_id,source_event_digest) DO NOTHING
               RETURNING *""",
            delivery.tenant_id,
            delivery.trigger_id,
            delivery.source_event_digest,
            delivery.status,
            delivery.authority_subject,
            delivery.run_id,
            delivery.hitl_request_id,
            delivery.reason,
            delivery.created_at,
        )
        if row is not None:
            return _delivery(row), True
        existing = await self.get_workflow_trigger_delivery(
            delivery.tenant_id,
            delivery.trigger_id,
            delivery.source_event_digest,
        )
        return existing, False

    async def get_workflow_trigger_delivery(
        self, tenant_id, trigger_id, source_event_digest
    ):
        row = await self._pool.fetchrow(
            """SELECT * FROM workflow_trigger_deliveries
               WHERE tenant_id=$1 AND trigger_id=$2 AND source_event_digest=$3""",
            tenant_id,
            trigger_id,
            source_event_digest,
        )
        return _delivery(row)

    async def list_workflow_trigger_deliveries(
        self, tenant_id, trigger_id, *, limit=20
    ):
        rows = await self._pool.fetch(
            """SELECT * FROM workflow_trigger_deliveries
               WHERE tenant_id=$1 AND trigger_id=$2
               ORDER BY created_at DESC,source_event_digest
               LIMIT $3""",
            tenant_id,
            trigger_id,
            max(0, min(limit, 100)),
        )
        return [_delivery(row) for row in rows]


def _memory_tables(store):
    triggers = getattr(store, "_workflow_triggers", None)
    deliveries = getattr(store, "_workflow_trigger_deliveries", None)
    lock = getattr(store, "_workflow_trigger_lock", None)
    if triggers is None:
        triggers = {}
        store._workflow_triggers = triggers
    if deliveries is None:
        deliveries = {}
        store._workflow_trigger_deliveries = deliveries
    if lock is None:
        lock = Lock()
        store._workflow_trigger_lock = lock
    return triggers, deliveries, lock


def _copy_trigger(trigger):
    return replace(
        trigger,
        grant_ceiling=GrantSet.of(
            list(trigger.grant_ceiling.allow), list(trigger.grant_ceiling.deny)
        ),
    )


class WorkflowTriggerStoreMem:
    async def create_workflow_trigger(self, trigger):
        triggers, _, lock = _memory_tables(self)
        key = (trigger.tenant_id, trigger.id)
        with lock:
            if key in triggers:
                return False
            now = utcnow()
            triggers[key] = _copy_trigger(
                replace(
                    trigger,
                    created_at=trigger.created_at or now,
                    updated_at=trigger.updated_at or now,
                )
            )
            return True

    async def get_workflow_trigger(self, tenant_id, trigger_id):
        triggers, _, _ = _memory_tables(self)
        trigger = triggers.get((tenant_id, trigger_id))
        return _copy_trigger(trigger) if trigger is not None else None

    async def list_workflow_triggers(self, tenant_id, workflow_id):
        triggers, _, _ = _memory_tables(self)
        rows = [
            row
            for (tenant, _), row in triggers.items()
            if tenant == tenant_id and row.workflow_id == workflow_id
        ]
        return [
            _copy_trigger(row)
            for row in sorted(rows, key=lambda row: (row.created_at, row.id))
        ]

    async def list_channel_workflow_triggers(
        self, tenant_id, channel_id, *, limit=32
    ):
        triggers, _, _ = _memory_tables(self)
        rows = [
            row
            for (tenant, _), row in triggers.items()
            if tenant == tenant_id
            and row.channel_id == channel_id
            and row.source == "channel"
            and row.enabled
        ]
        rows.sort(key=lambda row: (row.created_at, row.id))
        return [_copy_trigger(row) for row in rows[: max(0, min(limit, 32))]]

    async def set_workflow_trigger_enabled(
        self, tenant_id, trigger_id, enabled
    ):
        triggers, _, lock = _memory_tables(self)
        key = (tenant_id, trigger_id)
        with lock:
            trigger = triggers.get(key)
            if trigger is None:
                return None
            trigger = replace(trigger, enabled=bool(enabled), updated_at=utcnow())
            triggers[key] = trigger
            return _copy_trigger(trigger)

    async def rotate_workflow_trigger_secret(
        self, tenant_id, trigger_id, secret_hash
    ):
        triggers, _, lock = _memory_tables(self)
        key = (tenant_id, trigger_id)
        with lock:
            trigger = triggers.get(key)
            if trigger is None or trigger.source != "webhook":
                return None
            trigger = replace(
                trigger, secret_hash=secret_hash, updated_at=utcnow()
            )
            triggers[key] = trigger
            return _copy_trigger(trigger)

    async def record_workflow_trigger_delivery(self, delivery):
        _, deliveries, lock = _memory_tables(self)
        key = (
            delivery.tenant_id,
            delivery.trigger_id,
            delivery.source_event_digest,
        )
        with lock:
            existing = deliveries.get(key)
            if existing is not None:
                return replace(existing), False
            saved = replace(
                delivery, created_at=delivery.created_at or utcnow()
            )
            deliveries[key] = saved
            return replace(saved), True

    async def get_workflow_trigger_delivery(
        self, tenant_id, trigger_id, source_event_digest
    ):
        _, deliveries, _ = _memory_tables(self)
        item = deliveries.get((tenant_id, trigger_id, source_event_digest))
        return replace(item) if item is not None else None

    async def list_workflow_trigger_deliveries(
        self, tenant_id, trigger_id, *, limit=20
    ):
        _, deliveries, _ = _memory_tables(self)
        rows = [
            row
            for (tenant, bound_trigger, _), row in deliveries.items()
            if tenant == tenant_id and bound_trigger == trigger_id
        ]
        rows.sort(
            key=lambda row: (row.created_at, row.source_event_digest),
            reverse=True,
        )
        return [replace(row) for row in rows[: max(0, min(limit, 100))]]
