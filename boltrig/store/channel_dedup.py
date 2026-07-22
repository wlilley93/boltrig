"""Channel delivery dedup store domain (decision 0003, Phase 2; M3/SEC-66).

Durable, store-backed replay dedup for channel intake - the follow-on the
process-local seen-set in ``adapters/builtin/inbound_webhook.py`` always named.
A signed request replays with a genuine signature, so the signature check
cannot stop a second ingest; the dedup marker must survive worker restarts and
be atomic across concurrent workers, so it lives in the store.

``record_channel_delivery`` is a record-AND-check in one atomic step (PG:
``INSERT ... ON CONFLICT DO NOTHING``; Mem: no await between read and write,
mirroring ``consume_hitl``). Markers are tenant-scoped (RLS) and TTL-bounded;
expired markers are evicted opportunistically on write, matching the
process-local idiom.

Host-class contract:
  - ``ChannelDedupStorePG`` uses ``self._pool`` (an asyncpg pool).
  - ``ChannelDedupStoreMem`` uses ``self._chan_deliveries`` (a dict,
    initialised by InMemoryStore.__init__).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from boltrig.models import utcnow


class ChannelDedupStorePG:
    """Delivery-dedup methods for ``PostgresStore`` (uses ``self._pool``)."""

    async def record_channel_delivery(
        self, tenant_id, channel_id, delivery_id, *, ttl_seconds
    ) -> bool:
        # Atomic record-and-check: True when this is the FIRST sighting (the
        # marker row was inserted), False on a replay within the TTL window.
        await self._pool.execute(
            "DELETE FROM channel_deliveries WHERE tenant_id=$1 AND expires_at < now()",
            tenant_id,
        )
        row = await self._pool.fetchrow(
            """INSERT INTO channel_deliveries
                 (tenant_id, channel_id, delivery_id, seen_at, expires_at)
               VALUES ($1,$2,$3,now(),now() + make_interval(secs => $4))
               ON CONFLICT (tenant_id, channel_id, delivery_id) DO NOTHING
               RETURNING delivery_id""",
            tenant_id, channel_id, delivery_id, float(ttl_seconds),
        )
        return row is not None


class ChannelDedupStoreMem:
    """Delivery-dedup methods for ``InMemoryStore`` (uses ``self._chan_deliveries``)."""

    async def record_channel_delivery(
        self, tenant_id, channel_id, delivery_id, *, ttl_seconds
    ) -> bool:
        # No await between the read and the write: the check-and-set is atomic
        # on the event loop (mirrors consume_hitl).
        now: datetime = utcnow()
        key = (tenant_id, channel_id, delivery_id)
        for stale, exp in [
            (k, e) for k, e in self._chan_deliveries.items()
            if k[0] == tenant_id and e < now
        ]:
            del self._chan_deliveries[stale]
        if key in self._chan_deliveries:
            return False
        self._chan_deliveries[key] = now + timedelta(seconds=ttl_seconds)
        return True
