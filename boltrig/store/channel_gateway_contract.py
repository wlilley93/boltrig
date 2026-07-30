"""Persistence contract for gateway observations and owner leases."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from boltrig.models import ChannelGatewayLease, ChannelGatewayStatus


class ChannelGatewayStateContract(Protocol):
    async def upsert_channel_gateway_status(
        self, status: ChannelGatewayStatus
    ) -> None: ...

    async def list_channel_gateway_statuses(
        self, tenant_id: str
    ) -> list[ChannelGatewayStatus]: ...

    async def delete_channel_gateway_status(
        self, tenant_id: str, channel_id: str
    ) -> None: ...

    async def claim_channel_gateway_lease(
        self,
        tenant_id: str,
        channel_id: str,
        gateway_id: str,
        owner_lease_id: str,
        ttl_seconds: int,
        *,
        now: datetime | None = None,
    ) -> ChannelGatewayLease | None: ...

    async def channel_gateway_lease_owned(
        self,
        tenant_id: str,
        channel_id: str,
        owner_lease_id: str,
        *,
        minimum_remaining_seconds: int = 0,
        now: datetime | None = None,
    ) -> bool: ...

    async def list_channel_gateway_leases(
        self, tenant_id: str
    ) -> list[ChannelGatewayLease]: ...


__all__ = ["ChannelGatewayStateContract"]
