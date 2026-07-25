"""Channel outbox store domain (decision 0003, Phase 2).

Durable outbound delivery for the socket (persistent-connection) class. The
kernel holds no platform connection - the severed sidecar does - so
``channel.send`` on a socket channel enqueues a tenant-scoped outbox row and
the sidecar claims it over its run-scoped token, delivers, then acks (terminal)
or fails (retry with exponential backoff, terminal ``failed`` after the attempt
cap). The claim/ack/fail shape mirrors the work-item claim idiom (US-FLT-05):
an atomic pending -> in_flight transition with a lease so one sidecar wins,
an expired lease is reclaimable, and ack/fail are compare-and-swapped on the
lease owner so a stale claimer cannot settle another's delivery.

Host-class contract:
  - ``ChannelOutboxStorePG`` uses ``self._pool`` (an asyncpg pool).
  - ``ChannelOutboxStoreMem`` uses ``self._chan_outbox`` (a dict, initialised
    by InMemoryStore.__init__).
"""

from __future__ import annotations

from boltrig.models import ChannelOutboxMessage, utcnow

# Backoff multiplier ceiling: attempts grow unbounded across reclaim cycles, so
# the exponential factor is capped (max delay = backoff_seconds * 64).
_BACKOFF_CAP = 64


def _outbox_message(r):
    if r is None:
        return None
    return ChannelOutboxMessage(
        id=r["id"], tenant_id=r["tenant_id"], channel_id=r["channel_id"],
        payload=dict(r["payload"] or {}), status=r["status"], attempts=r["attempts"],
        lease_owner=r["lease_owner"], lease_expires_at=r["lease_expires_at"],
        next_attempt_at=r["next_attempt_at"], last_error=r["last_error"],
        created_at=r["created_at"], updated_at=r["updated_at"],
    )


class ChannelOutboxStorePG:
    """Channel outbox methods for ``PostgresStore`` (uses ``self._pool``)."""

    async def enqueue_channel_outbox(self, message):
        await self._pool.execute(
            """INSERT INTO channel_outbox
                 (id, tenant_id, channel_id, payload, status, attempts,
                  next_attempt_at, created_at, updated_at)
               VALUES ($1,$2,$3,$4,'pending',0,NULL,COALESCE($5, now()),now())""",
            message.id, message.tenant_id, message.channel_id, message.payload,
            message.created_at,
        )

    async def claim_channel_outbox(
        self, tenant_id, channel_ids, worker_id, lease_seconds, limit
    ):
        # Atomic pending -> in_flight batch claim with a lease (mirrors
        # claim_work_item): FOR UPDATE SKIP LOCKED so concurrent sidecars never
        # block or double-claim; an expired lease is reclaimable; a pending row
        # is due only once its backoff gate has passed. attempts increments per
        # claim. RETURNING tells us what we won.
        if not channel_ids:
            return []
        # The inner ORDER BY chooses WHICH rows to claim (oldest first). It does
        # NOT order the result: Postgres defines no ordering for RETURNING, so the
        # claim handed back the right messages in an arbitrary order while both
        # this module and the in-memory twin document "oldest first". For a
        # channel outbox that is user-visible message reordering, so the CTE
        # re-imposes the documented order on the way out.
        rows = await self._pool.fetch(
            """WITH claimed AS (
                 UPDATE channel_outbox
                 SET status='in_flight', lease_owner=$2,
                     lease_expires_at=now() + make_interval(secs => $3),
                     attempts=attempts+1, updated_at=now()
                 WHERE tenant_id=$1 AND id IN (
                   SELECT id FROM channel_outbox
                   WHERE tenant_id=$1 AND channel_id = ANY($4::text[])
                     AND ((status='pending'
                           AND (next_attempt_at IS NULL OR next_attempt_at <= now()))
                          OR (status='in_flight' AND lease_expires_at < now()))
                   ORDER BY created_at LIMIT $5 FOR UPDATE SKIP LOCKED
                 )
                 RETURNING *
               )
               SELECT * FROM claimed ORDER BY created_at, id""",
            tenant_id, worker_id, float(lease_seconds), list(channel_ids), limit,
        )
        return [_outbox_message(r) for r in rows]

    async def ack_channel_outbox(self, tenant_id, message_id, worker_id):
        # CAS: only the live lease owner settles its own claim (terminal).
        row = await self._pool.fetchrow(
            """UPDATE channel_outbox SET status='delivered', updated_at=now()
               WHERE tenant_id=$1 AND id=$2 AND status='in_flight'
                 AND lease_owner=$3 RETURNING id""",
            tenant_id, message_id, worker_id,
        )
        return row is not None

    async def fail_channel_outbox(
        self, tenant_id, message_id, worker_id, error, *, max_attempts, backoff_seconds
    ):
        # CAS on the lease owner. Under the attempt cap the row returns to
        # pending behind an exponential backoff gate; at the cap it is
        # terminally failed (a poison message never hot-loops).
        row = await self._pool.fetchrow(
            """UPDATE channel_outbox
               SET status = CASE WHEN attempts >= $5 THEN 'failed' ELSE 'pending' END,
                   next_attempt_at = CASE WHEN attempts >= $5 THEN next_attempt_at
                       ELSE now() + make_interval(secs =>
                           $6 * LEAST(power(2, attempts - 1), $7)) END,
                   lease_owner = NULL, lease_expires_at = NULL,
                   last_error = $4, updated_at = now()
               WHERE tenant_id=$1 AND id=$2 AND status='in_flight'
                 AND lease_owner=$3 RETURNING id""",
            tenant_id, message_id, worker_id, (error or "")[:500],
            max_attempts, float(backoff_seconds), float(_BACKOFF_CAP),
        )
        return row is not None


class ChannelOutboxStoreMem:
    """Channel outbox methods for ``InMemoryStore`` (uses ``self._chan_outbox``)."""

    async def enqueue_channel_outbox(self, message):
        message.status = "pending"
        self._chan_outbox[(message.tenant_id, message.id)] = message

    async def claim_channel_outbox(
        self, tenant_id, channel_ids, worker_id, lease_seconds, limit
    ):
        # No await between the scan and the write: the batch claim is atomic on
        # the event loop (mirrors claim_work_item); insertion order stands in
        # for the Postgres ORDER BY created_at (oldest first).
        from datetime import timedelta

        if not channel_ids:
            return []
        now = utcnow()
        wanted = set(channel_ids)
        claimed = []
        for (tenant, _), msg in self._chan_outbox.items():
            if len(claimed) >= limit:
                break
            if tenant != tenant_id or msg.channel_id not in wanted:
                continue
            due = msg.next_attempt_at is None or msg.next_attempt_at <= now
            claimable = (msg.status == "pending" and due) or (
                msg.status == "in_flight"
                and msg.lease_expires_at is not None
                and msg.lease_expires_at < now
            )
            if not claimable:
                continue
            msg.status = "in_flight"
            msg.lease_owner = worker_id
            msg.lease_expires_at = now + timedelta(seconds=lease_seconds)
            msg.attempts += 1
            msg.updated_at = now
            claimed.append(msg)
        return claimed

    async def ack_channel_outbox(self, tenant_id, message_id, worker_id):
        msg = self._chan_outbox.get((tenant_id, message_id))
        if msg is None or msg.status != "in_flight" or msg.lease_owner != worker_id:
            return False
        msg.status = "delivered"
        msg.updated_at = utcnow()
        return True

    async def fail_channel_outbox(
        self, tenant_id, message_id, worker_id, error, *, max_attempts, backoff_seconds
    ):
        from datetime import timedelta

        msg = self._chan_outbox.get((tenant_id, message_id))
        if msg is None or msg.status != "in_flight" or msg.lease_owner != worker_id:
            return False
        now = utcnow()
        if msg.attempts >= max_attempts:
            msg.status = "failed"  # terminal: a poison message never hot-loops
        else:
            msg.status = "pending"
            factor = min(2 ** (msg.attempts - 1), _BACKOFF_CAP)
            msg.next_attempt_at = now + timedelta(seconds=backoff_seconds * factor)
        msg.lease_owner = None
        msg.lease_expires_at = None
        msg.last_error = (error or "")[:500]
        msg.updated_at = now
        return True
