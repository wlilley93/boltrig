"""Channel store domain (arc-1 structural partial, decision 0003).

The channel store methods extracted from ``store/postgres.py`` +
``store/memory.py`` to bring both under the structural floor.
``PostgresStore`` mixes in :class:`ChannelStorePG`; ``InMemoryStore`` mixes in
:class:`ChannelStoreMem`. The public method surface (the Store Protocol in
``base.py``) is unchanged - this is a pure structural relocation, behaviour- and
symmetry-preserving.

Host-class contract:
  - ``ChannelStorePG`` uses ``self._pool`` (an asyncpg pool, set by PostgresStore).
  - ``ChannelStoreMem`` uses ``self._channels`` / ``self._chan_bindings`` /
    ``self._chan_pairings`` (dicts, initialised by InMemoryStore.__init__).
"""

from __future__ import annotations

from boltrig.models import Channel, ChannelBinding, ChannelPairing


# --- Postgres row mappers (moved verbatim from store/postgres.py) ---


def _channel(r):
    if r is None:
        return None
    return Channel(
        id=r["id"], tenant_id=r["tenant_id"], platform=r["platform"], name=r["name"],
        transport=r["transport"], credential_ref=r["credential_ref"],
        config=dict(r["config"] or {}), unpaired_behavior=r["unpaired_behavior"],
        enabled=r["enabled"], created_at=r["created_at"],
    )


def _channel_binding(r):
    if r is None:
        return None
    return ChannelBinding(
        id=r["id"], tenant_id=r["tenant_id"], channel_id=r["channel_id"], platform=r["platform"],
        external_user_id=r["external_user_id"], subject=r["subject"], role=r["role"],
        created_at=r["created_at"],
    )


def _channel_pairing(r):
    if r is None:
        return None
    return ChannelPairing(
        id=r["id"], tenant_id=r["tenant_id"], channel_id=r["channel_id"], code_hash=r["code_hash"],
        external_user_id=r["external_user_id"], subject=r["subject"], role=r["role"],
        status=r["status"], attempts=r["attempts"],
        expires_at=r["expires_at"], created_at=r["created_at"],
    )


class ChannelStorePG:
    """Channel methods for ``PostgresStore`` (uses ``self._pool``)."""

    async def upsert_channel(self, channel):
        await self._pool.execute(
            """INSERT INTO channels
                 (id, tenant_id, platform, name, transport, credential_ref, config,
                  unpaired_behavior, enabled, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,COALESCE($10, now()))
               ON CONFLICT (id) DO UPDATE SET
                 platform=EXCLUDED.platform, name=EXCLUDED.name, transport=EXCLUDED.transport,
                 credential_ref=EXCLUDED.credential_ref, config=EXCLUDED.config,
                 unpaired_behavior=EXCLUDED.unpaired_behavior, enabled=EXCLUDED.enabled
               WHERE channels.tenant_id = EXCLUDED.tenant_id""",
            channel.id, channel.tenant_id, channel.platform, channel.name, channel.transport,
            channel.credential_ref, channel.config, channel.unpaired_behavior, channel.enabled,
            channel.created_at,
        )

    async def get_channel(self, tenant_id, channel_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM channels WHERE id=$1 AND tenant_id=$2", channel_id, tenant_id
        )
        return _channel(row)

    async def get_channel_by_id(self, channel_id):
        # cross-tenant inbound lookup by the unguessable id (channels is RLS-excluded)
        row = await self._pool.fetchrow("SELECT * FROM channels WHERE id=$1", channel_id)
        return _channel(row)

    async def list_channels(self, tenant_id):
        rows = await self._pool.fetch(
            "SELECT * FROM channels WHERE tenant_id=$1 ORDER BY name", tenant_id
        )
        return [_channel(r) for r in rows]

    async def delete_channel(self, tenant_id, channel_id):
        # bindings + pairings cascade via FK ON DELETE CASCADE (schema.sql)
        await self._pool.execute(
            "DELETE FROM channels WHERE id=$1 AND tenant_id=$2", channel_id, tenant_id
        )

    async def upsert_channel_binding(self, binding):
        await self._pool.execute(
            """INSERT INTO channel_bindings
                 (id, tenant_id, channel_id, platform, external_user_id, subject, role, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,COALESCE($8, now()))
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 subject=EXCLUDED.subject, role=EXCLUDED.role""",
            binding.id, binding.tenant_id, binding.channel_id, binding.platform,
            binding.external_user_id, binding.subject, binding.role, binding.created_at,
        )

    async def get_channel_binding(self, tenant_id, channel_id, external_user_id):
        row = await self._pool.fetchrow(
            """SELECT * FROM channel_bindings
               WHERE tenant_id=$1 AND channel_id=$2 AND external_user_id=$3""",
            tenant_id, channel_id, external_user_id,
        )
        return _channel_binding(row)

    async def list_channel_bindings(self, tenant_id, channel_id):
        rows = await self._pool.fetch(
            "SELECT * FROM channel_bindings WHERE tenant_id=$1 AND channel_id=$2",
            tenant_id, channel_id,
        )
        return [_channel_binding(r) for r in rows]

    async def delete_channel_binding(self, tenant_id, binding_id):
        await self._pool.execute(
            "DELETE FROM channel_bindings WHERE tenant_id=$1 AND id=$2", tenant_id, binding_id
        )

    async def create_channel_pairing(self, pairing):
        await self._pool.execute(
            """INSERT INTO channel_pairings
                 (id, tenant_id, channel_id, code_hash, external_user_id, subject, role,
                  status, attempts, expires_at, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,COALESCE($11, now()))""",
            pairing.id, pairing.tenant_id, pairing.channel_id, pairing.code_hash,
            pairing.external_user_id, pairing.subject, pairing.role,
            pairing.status, pairing.attempts, pairing.expires_at, pairing.created_at,
        )

    async def get_channel_pairing_by_code(self, tenant_id, channel_id, code_hash):
        row = await self._pool.fetchrow(
            """SELECT * FROM channel_pairings
               WHERE tenant_id=$1 AND channel_id=$2 AND code_hash=$3 AND status='pending'""",
            tenant_id, channel_id, code_hash,
        )
        return _channel_pairing(row)

    async def consume_channel_pairing(self, tenant_id, pairing_id):
        # atomic pending -> consumed CAS (single-use; mirrors consume_hitl)
        row = await self._pool.fetchrow(
            """UPDATE channel_pairings SET status='consumed'
               WHERE tenant_id=$1 AND id=$2 AND status='pending' RETURNING id""",
            tenant_id, pairing_id,
        )
        return row is not None

    async def get_pending_pairing_for_sender(self, tenant_id, channel_id, external_user_id):
        row = await self._pool.fetchrow(
            """SELECT * FROM channel_pairings
               WHERE tenant_id=$1 AND channel_id=$2 AND external_user_id=$3
                 AND status='pending' ORDER BY created_at DESC LIMIT 1""",
            tenant_id, channel_id, external_user_id,
        )
        return _channel_pairing(row)

    async def bump_channel_pairing_attempts(self, tenant_id, pairing_id, *, cap):
        # increment attempts; flip to 'expired' once the cap is hit (lockout).
        row = await self._pool.fetchrow(
            """UPDATE channel_pairings
                  SET attempts = attempts + 1,
                      status = CASE WHEN attempts + 1 >= $3 THEN 'expired' ELSE status END
                WHERE tenant_id=$1 AND id=$2 AND status='pending' RETURNING *""",
            tenant_id, pairing_id, cap,
        )
        return _channel_pairing(row)


class ChannelStoreMem:
    """Channel methods for ``InMemoryStore`` (uses ``self._channels`` etc.)."""

    async def upsert_channel(self, channel):
        # Same-tenant upsert only (mirrors the PG ON CONFLICT ... WHERE tenant
        # predicate): a conflicting id from another tenant is a no-op, never a
        # re-key of credential_ref/config across the tenant boundary.
        existing = self._channels.get(channel.id)
        if existing is None or existing.tenant_id == channel.tenant_id:
            self._channels[channel.id] = channel

    async def get_channel(self, tenant_id, channel_id):
        c = self._channels.get(channel_id)
        return c if c and c.tenant_id == tenant_id else None

    async def get_channel_by_id(self, channel_id):
        return self._channels.get(channel_id)

    async def list_channels(self, tenant_id):
        return sorted(
            [c for c in self._channels.values() if c.tenant_id == tenant_id],
            key=lambda c: c.name,
        )

    async def delete_channel(self, tenant_id, channel_id):
        c = self._channels.get(channel_id)
        if c and c.tenant_id == tenant_id:
            del self._channels[channel_id]
            for k in [k for k, b in self._chan_bindings.items() if b.channel_id == channel_id]:
                self._chan_bindings.pop(k, None)
            for k in [k for k, p in self._chan_pairings.items() if p.channel_id == channel_id]:
                self._chan_pairings.pop(k, None)

    async def upsert_channel_binding(self, binding):
        self._chan_bindings[(binding.tenant_id, binding.id)] = binding

    async def get_channel_binding(self, tenant_id, channel_id, external_user_id):
        for b in self._chan_bindings.values():
            if (
                b.tenant_id == tenant_id
                and b.channel_id == channel_id
                and b.external_user_id == external_user_id
            ):
                return b
        return None

    async def list_channel_bindings(self, tenant_id, channel_id):
        return [
            b
            for b in self._chan_bindings.values()
            if b.tenant_id == tenant_id and b.channel_id == channel_id
        ]

    async def delete_channel_binding(self, tenant_id, binding_id):
        self._chan_bindings.pop((tenant_id, binding_id), None)

    async def create_channel_pairing(self, pairing):
        self._chan_pairings[(pairing.tenant_id, pairing.id)] = pairing

    async def get_channel_pairing_by_code(self, tenant_id, channel_id, code_hash):
        for p in self._chan_pairings.values():
            if (
                p.tenant_id == tenant_id
                and p.channel_id == channel_id
                and p.code_hash == code_hash
                and p.status == "pending"
            ):
                return p
        return None

    async def consume_channel_pairing(self, tenant_id, pairing_id):
        p = self._chan_pairings.get((tenant_id, pairing_id))
        if p is None or p.status != "pending":
            return False
        p.status = "consumed"
        return True

    async def get_pending_pairing_for_sender(self, tenant_id, channel_id, external_user_id):
        matches = [
            p
            for p in self._chan_pairings.values()
            if (
                p.tenant_id == tenant_id
                and p.channel_id == channel_id
                and p.external_user_id == external_user_id
                and p.status == "pending"
            )
        ]
        # Newest first, matching the PG ORDER BY created_at DESC LIMIT 1.
        return max(matches, key=lambda p: p.created_at, default=None)

    async def bump_channel_pairing_attempts(self, tenant_id, pairing_id, *, cap):
        p = self._chan_pairings.get((tenant_id, pairing_id))
        if p is None or p.status != "pending":
            return None
        p.attempts += 1
        if p.attempts >= cap:
            p.status = "expired"  # lockout: cap hit -> unusable
        return p
