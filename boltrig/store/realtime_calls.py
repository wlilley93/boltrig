"""Tenant-scoped persistence for realtime call metadata and normalized events."""

from __future__ import annotations

import secrets
from dataclasses import replace

from boltrig.models import RealtimeCallEvent, RealtimeCallSession, utcnow
from .device_memory import DeviceStoreMem
from .device_pg import DeviceStorePG
from .camera_memory import CameraStoreMem
from .camera_pg import CameraStorePG
from .artifacts import ArtifactStoreMem, ArtifactStorePG
from .integrations import IntegrationStoreMem, IntegrationStorePG
from .realtime_call_usage import USAGE_COUNTERS, nonnegative_int, usage_summary


def _call_session(row):
    if row is None:
        return None
    return RealtimeCallSession(
        id=row["id"],
        tenant_id=row["tenant_id"],
        conversation_id=row["conversation_id"],
        owner_id=row["owner_id"],
        channel_id=row["channel_id"],
        status=row["status"],
        participants=list(row["participants"] or []),
        tool_context=dict(row["tool_context"] or {}),
        provider_class=row["provider_class"],
        run_id=row["run_id"],
        agent_profile_id=row["agent_profile_id"],
        model_profile_id=row["model_profile_id"],
        media_token_hash=row["media_token_hash"],
        media_token_expires_at=row["media_token_expires_at"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        unavailable_reason=row["unavailable_reason"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _call_event(row):
    if row is None:
        return None
    return RealtimeCallEvent(
        id=row["id"],
        tenant_id=row["tenant_id"],
        call_id=row["call_id"],
        type=row["type"],
        payload=dict(row["payload"] or {}),
        participant_id=row["participant_id"],
        created_at=row["created_at"],
    )


class RealtimeCallStorePG(ArtifactStorePG, IntegrationStorePG, DeviceStorePG, CameraStorePG):
    """Postgres implementation. Every lookup is tenant-keyed."""

    async def create_realtime_call(self, call):
        await self._pool.execute(
            """INSERT INTO realtime_calls
                 (id, tenant_id, conversation_id, owner_id, channel_id, status,
                  participants, tool_context, provider_class, run_id,
                  agent_profile_id, model_profile_id, media_token_hash,
                  media_token_expires_at, started_at, ended_at,
                  unavailable_reason, created_at, updated_at)
               VALUES
                 ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)
               ON CONFLICT (tenant_id, id) DO NOTHING""",
            call.id,
            call.tenant_id,
            call.conversation_id,
            call.owner_id,
            call.channel_id,
            call.status,
            call.participants,
            call.tool_context,
            call.provider_class,
            call.run_id,
            call.agent_profile_id,
            call.model_profile_id,
            call.media_token_hash,
            call.media_token_expires_at,
            call.started_at,
            call.ended_at,
            call.unavailable_reason,
            call.created_at,
            call.updated_at,
        )

    async def get_realtime_call(self, tenant_id, call_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM realtime_calls WHERE tenant_id=$1 AND id=$2",
            tenant_id,
            call_id,
        )
        return _call_session(row)

    async def list_realtime_calls(
        self, tenant_id, owner_id, limit=50, conversation_id=None
    ):
        bounded = max(1, min(int(limit), 100))
        rows = await self._pool.fetch(
            """SELECT * FROM realtime_calls
                WHERE tenant_id=$1 AND owner_id=$2
                  AND ($3::text IS NULL OR conversation_id=$3)
                ORDER BY updated_at DESC, id DESC LIMIT $4""",
            tenant_id, owner_id, conversation_id, bounded,
        )
        return [_call_session(row) for row in rows]

    async def get_current_realtime_call(
        self, tenant_id, owner_id, conversation_id=None
    ):
        row = await self._pool.fetchrow(
            """SELECT * FROM realtime_calls
                WHERE tenant_id=$1 AND owner_id=$2
                  AND ($3::text IS NULL OR conversation_id=$3)
                  AND status IN ('creating','joining','active','reconnecting','held')
                ORDER BY updated_at DESC, id DESC LIMIT 1""",
            tenant_id, owner_id, conversation_id,
        )
        return _call_session(row)

    async def update_realtime_call(self, call):
        await self._pool.execute(
            """UPDATE realtime_calls
                  SET status=$3, participants=$4, tool_context=$5, run_id=$6,
                      media_token_hash=$7, media_token_expires_at=$8,
                      started_at=$9, ended_at=$10, unavailable_reason=$11,
                      updated_at=$12
                WHERE tenant_id=$1 AND id=$2""",
            call.tenant_id,
            call.id,
            call.status,
            call.participants,
            call.tool_context,
            call.run_id,
            call.media_token_hash,
            call.media_token_expires_at,
            call.started_at,
            call.ended_at,
            call.unavailable_reason,
            call.updated_at,
        )

    async def claim_realtime_call_media(
        self, tenant_id, call_id, channel_ids, token_hash
    ):
        if not channel_ids:
            return None
        row = await self._pool.fetchrow(
            """UPDATE realtime_calls
                  SET status='active', media_token_hash=NULL,
                      media_token_expires_at=NULL,
                      started_at=COALESCE(started_at, now()), updated_at=now()
                WHERE tenant_id=$1 AND id=$2
                  AND channel_id=ANY($3::text[])
                  AND media_token_hash=$4
                  AND media_token_expires_at >= now()
                  AND status IN ('creating','joining','reconnecting')
                RETURNING *""",
            tenant_id,
            call_id,
            list(channel_ids),
            token_hash,
        )
        return _call_session(row)

    async def append_realtime_call_event(self, event):
        # A cross-tenant call id cannot receive an event from ``append_realtime_call_event``
        # because the FK includes tenant_id.
        # Replayed event ids are no-ops.
        await self._pool.execute(
            """INSERT INTO realtime_call_events
                 (id, tenant_id, call_id, type, participant_id, payload, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7)
               ON CONFLICT (tenant_id, id) DO NOTHING""",
            event.id,
            event.tenant_id,
            event.call_id,
            event.type,
            event.participant_id,
            event.payload,
            event.created_at,
        )

    async def list_realtime_call_events(self, tenant_id, call_id, limit=500):
        bounded = max(1, min(int(limit), 500))
        rows = await self._pool.fetch(
            """SELECT * FROM realtime_call_events
                WHERE tenant_id=$1 AND call_id=$2
                ORDER BY created_at, id LIMIT $3""",
            tenant_id,
            call_id,
            bounded,
        )
        return [_call_event(row) for row in rows]

    async def get_realtime_call_hitl_event(
        self, tenant_id, call_id, request_id
    ):
        row = await self._pool.fetchrow(
            """SELECT * FROM realtime_call_events
                WHERE tenant_id=$1 AND call_id=$2 AND type='hitl'
                  AND payload->>'request_id'=$3
                ORDER BY (payload->>'status' = 'pending') ASC,
                         created_at DESC, id DESC LIMIT 1""",
            tenant_id,
            call_id,
            request_id,
        )
        return _call_event(row)

    async def summarize_realtime_call_usage(self, tenant_id, call_id):
        row = await self._pool.fetchrow(
            """SELECT
                 COALESCE(SUM((payload->>'input_audio_bytes')::bigint), 0) AS input_audio_bytes,
                 COALESCE(SUM((payload->>'output_audio_bytes')::bigint), 0) AS output_audio_bytes,
                 COALESCE(SUM((payload->>'tool_calls')::bigint), 0) AS tool_calls,
                 COALESCE(SUM((payload->>'provider_input_tokens')::bigint), 0) AS provider_input_tokens,
                 COALESCE(SUM((payload->>'provider_output_tokens')::bigint), 0) AS provider_output_tokens,
                 COALESCE(SUM((payload->>'estimated_cost_micros')::bigint), 0) AS estimated_cost_micros,
                 MAX(payload->>'pricing_revision') AS pricing_revision,
                 CASE
                   WHEN COUNT(*) FILTER (WHERE payload->>'cost_status' = 'estimated') > 0
                   THEN 'estimated' ELSE 'unpriced'
                 END AS cost_status
               FROM realtime_call_events
              WHERE tenant_id=$1 AND call_id=$2 AND type='usage'""",
            tenant_id,
            call_id,
        )
        return usage_summary(row)


class RealtimeCallStoreMem(ArtifactStoreMem, IntegrationStoreMem, DeviceStoreMem, CameraStoreMem):
    """In-memory reference implementation with the same tenant and token fences."""

    async def create_realtime_call(self, call):
        calls, _ = _memory_tables(self)
        calls.setdefault((call.tenant_id, call.id), call)

    async def get_realtime_call(self, tenant_id, call_id):
        calls, _ = _memory_tables(self)
        call = calls.get((tenant_id, call_id))
        return replace(call) if call is not None else None

    async def list_realtime_calls(
        self, tenant_id, owner_id, limit=50, conversation_id=None
    ):
        bounded = max(1, min(int(limit), 100))
        calls, _ = _memory_tables(self)
        rows = [
            call for call in calls.values()
            if call.tenant_id == tenant_id
            and call.owner_id == owner_id
            and (conversation_id is None or call.conversation_id == conversation_id)
        ]
        return [
            replace(call)
            for call in sorted(
                rows, key=lambda call: (call.updated_at, call.id), reverse=True
            )[:bounded]
        ]

    async def get_current_realtime_call(
        self, tenant_id, owner_id, conversation_id=None
    ):
        rows = await self.list_realtime_calls(
            tenant_id, owner_id, 100, conversation_id
        )
        return next(
            (
                call for call in rows
                if call.status in {
                    "creating", "joining", "active", "reconnecting", "held"
                }
            ),
            None,
        )

    async def update_realtime_call(self, call):
        key = (call.tenant_id, call.id)
        calls, _ = _memory_tables(self)
        if key in calls:
            calls[key] = replace(call)

    async def claim_realtime_call_media(
        self, tenant_id, call_id, channel_ids, token_hash
    ):
        key = (tenant_id, call_id)
        calls, _ = _memory_tables(self)
        call = calls.get(key)
        now = utcnow()
        if (
            call is None
            or call.channel_id not in set(channel_ids)
            or call.status not in {"creating", "joining", "reconnecting"}
            or call.media_token_hash is None
            or call.media_token_expires_at is None
            or call.media_token_expires_at < now
            or not secrets.compare_digest(call.media_token_hash, token_hash)
        ):
            return None
        claimed = replace(
            call,
            status="active",
            media_token_hash=None,
            media_token_expires_at=None,
            started_at=call.started_at or now,
            updated_at=now,
        )
        calls[key] = claimed
        return replace(claimed)

    async def append_realtime_call_event(self, event):
        calls, event_rows = _memory_tables(self)
        if (event.tenant_id, event.call_id) not in calls:
            return
        rows = event_rows.setdefault(
            (event.tenant_id, event.call_id), []
        )
        if not any(row.id == event.id for row in rows):
            rows.append(replace(event))

    async def list_realtime_call_events(self, tenant_id, call_id, limit=500):
        bounded = max(1, min(int(limit), 500))
        _, event_rows = _memory_tables(self)
        rows = event_rows.get((tenant_id, call_id), [])
        return [replace(row) for row in sorted(
            rows, key=lambda row: (row.created_at, row.id)
        )[:bounded]]

    async def get_realtime_call_hitl_event(
        self, tenant_id, call_id, request_id
    ):
        _, event_rows = _memory_tables(self)
        matches = [
            row
            for row in event_rows.get((tenant_id, call_id), [])
            if row.type == "hitl" and row.payload.get("request_id") == request_id
        ]
        if not matches:
            return None
        terminal = [row for row in matches if row.payload.get("status") != "pending"]
        return replace(max(terminal or matches, key=lambda row: (row.created_at, row.id)))

    async def summarize_realtime_call_usage(self, tenant_id, call_id):
        _, event_rows = _memory_tables(self)
        rows = [
            row.payload
            for row in event_rows.get((tenant_id, call_id), [])
            if row.type == "usage"
        ]
        return {
            key: sum(nonnegative_int(row.get(key)) for row in rows)
            for key in USAGE_COUNTERS
        } | {
            "pricing_revision": next(
                (
                    str(row["pricing_revision"])
                    for row in reversed(rows)
                    if row.get("pricing_revision")
                ),
                None,
            ),
            "cost_status": (
                "estimated"
                if any(row.get("cost_status") == "estimated" for row in rows)
                else "unpriced"
            ),
        }


def _memory_tables(store):
    """Lazily attach the two maps so InMemoryStore.__init__ does not grow."""
    calls = getattr(store, "_realtime_calls", None)
    events = getattr(store, "_realtime_call_events", None)
    if calls is None:
        calls = {}
        store._realtime_calls = calls
    if events is None:
        events = {}
        store._realtime_call_events = events
    return calls, events
