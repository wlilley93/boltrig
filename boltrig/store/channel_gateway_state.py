"""Desired/observed state and durable owner leases for channel gateways."""

from __future__ import annotations

from datetime import timedelta

from boltrig.models import ChannelGatewayLease, ChannelGatewayStatus, utcnow


def _status(row):
    if row is None:
        return None
    return ChannelGatewayStatus(
        tenant_id=row["tenant_id"],
        channel_id=row["channel_id"],
        gateway_id=row["gateway_id"],
        desired_revision=row["desired_revision"],
        observed_revision=row["observed_revision"],
        status=row["status"],
        reason_code=row["reason_code"],
        observed_at=row["observed_at"],
    )


def _lease(row):
    if row is None:
        return None
    return ChannelGatewayLease(
        tenant_id=row["tenant_id"],
        channel_id=row["channel_id"],
        gateway_id=row["gateway_id"],
        owner_lease_id=row["owner_lease_id"],
        lease_expires_at=row["lease_expires_at"],
        updated_at=row["updated_at"],
    )


class ChannelGatewayStatePG:
    async def upsert_channel_gateway_status(self, status):
        await self._pool.execute(
            """INSERT INTO channel_gateway_status
                 (tenant_id, channel_id, gateway_id, desired_revision,
                  observed_revision, status, reason_code, observed_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,COALESCE($8, now()))
               ON CONFLICT (tenant_id, channel_id) DO UPDATE SET
                 gateway_id=EXCLUDED.gateway_id,
                 desired_revision=EXCLUDED.desired_revision,
                 observed_revision=EXCLUDED.observed_revision,
                 status=EXCLUDED.status,
                 reason_code=EXCLUDED.reason_code,
                 observed_at=EXCLUDED.observed_at""",
            status.tenant_id,
            status.channel_id,
            status.gateway_id,
            status.desired_revision,
            status.observed_revision,
            status.status,
            status.reason_code,
            status.observed_at,
        )

    async def list_channel_gateway_statuses(self, tenant_id):
        rows = await self._pool.fetch(
            """SELECT * FROM channel_gateway_status
               WHERE tenant_id=$1 ORDER BY channel_id""",
            tenant_id,
        )
        return [_status(row) for row in rows]

    async def delete_channel_gateway_status(self, tenant_id, channel_id):
        await self._pool.execute(
            """DELETE FROM channel_gateway_status
               WHERE tenant_id=$1 AND channel_id=$2""",
            tenant_id,
            channel_id,
        )

    async def claim_channel_gateway_lease(
        self,
        tenant_id,
        channel_id,
        gateway_id,
        owner_lease_id,
        ttl_seconds,
        *,
        now=None,
    ):
        now = now or utcnow()
        row = await self._pool.fetchrow(
            """INSERT INTO channel_gateway_leases
                 (tenant_id, channel_id, gateway_id, owner_lease_id,
                  lease_expires_at, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6)
               ON CONFLICT (tenant_id, channel_id) DO UPDATE SET
                 gateway_id=EXCLUDED.gateway_id,
                 owner_lease_id=EXCLUDED.owner_lease_id,
                 lease_expires_at=EXCLUDED.lease_expires_at,
                 updated_at=EXCLUDED.updated_at
               WHERE
                 channel_gateway_leases.owner_lease_id=EXCLUDED.owner_lease_id
                 OR channel_gateway_leases.lease_expires_at <= $6
               RETURNING *""",
            tenant_id,
            channel_id,
            gateway_id,
            owner_lease_id,
            now + timedelta(seconds=ttl_seconds),
            now,
        )
        return _lease(row)

    async def channel_gateway_lease_owned(
        self,
        tenant_id,
        channel_id,
        owner_lease_id,
        *,
        minimum_remaining_seconds=0,
        now=None,
    ):
        threshold = (now or utcnow()) + timedelta(
            seconds=minimum_remaining_seconds
        )
        return bool(
            await self._pool.fetchval(
                """SELECT EXISTS (
                     SELECT 1 FROM channel_gateway_leases
                     WHERE tenant_id=$1 AND channel_id=$2
                       AND owner_lease_id=$3
                       AND lease_expires_at > $4
                   )""",
                tenant_id,
                channel_id,
                owner_lease_id,
                threshold,
            )
        )

    async def list_channel_gateway_leases(self, tenant_id):
        rows = await self._pool.fetch(
            """SELECT * FROM channel_gateway_leases
               WHERE tenant_id=$1 ORDER BY channel_id""",
            tenant_id,
        )
        return [_lease(row) for row in rows]


class ChannelGatewayStateMem:
    async def upsert_channel_gateway_status(self, status):
        self._chan_gateway_status[(status.tenant_id, status.channel_id)] = status

    async def list_channel_gateway_statuses(self, tenant_id):
        return sorted(
            [
                status
                for (row_tenant, _), status in self._chan_gateway_status.items()
                if row_tenant == tenant_id
            ],
            key=lambda status: status.channel_id,
        )

    async def delete_channel_gateway_status(self, tenant_id, channel_id):
        self._chan_gateway_status.pop((tenant_id, channel_id), None)

    async def claim_channel_gateway_lease(
        self,
        tenant_id,
        channel_id,
        gateway_id,
        owner_lease_id,
        ttl_seconds,
        *,
        now=None,
    ):
        now = now or utcnow()
        key = (tenant_id, channel_id)
        current = self._chan_gateway_leases.get(key)
        if (
            current is not None
            and current.owner_lease_id != owner_lease_id
            and current.lease_expires_at > now
        ):
            return None
        lease = ChannelGatewayLease(
            tenant_id=tenant_id,
            channel_id=channel_id,
            gateway_id=gateway_id,
            owner_lease_id=owner_lease_id,
            lease_expires_at=now + timedelta(seconds=ttl_seconds),
            updated_at=now,
        )
        self._chan_gateway_leases[key] = lease
        return lease

    async def channel_gateway_lease_owned(
        self,
        tenant_id,
        channel_id,
        owner_lease_id,
        *,
        minimum_remaining_seconds=0,
        now=None,
    ):
        now = now or utcnow()
        lease = self._chan_gateway_leases.get((tenant_id, channel_id))
        return bool(
            lease
            and lease.owner_lease_id == owner_lease_id
            and lease.lease_expires_at
            > now + timedelta(seconds=minimum_remaining_seconds)
        )

    async def list_channel_gateway_leases(self, tenant_id):
        return sorted(
            [
                lease
                for (row_tenant, _), lease in self._chan_gateway_leases.items()
                if row_tenant == tenant_id
            ],
            key=lambda lease: lease.channel_id,
        )


__all__ = ["ChannelGatewayStateMem", "ChannelGatewayStatePG"]
