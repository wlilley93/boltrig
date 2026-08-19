"""Persistence contract for enrolled desktop devices and exact-action leases."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from boltrig.models.devices import (
    DeviceEnrollment, DeviceLease, DeviceRoot, EnrolledDevice,
)


class DeviceStoreContract(Protocol):
    async def create_device_enrollment(self, enrollment: DeviceEnrollment) -> bool: ...
    async def complete_device_enrollment(
        self, tenant_id: str, enrollment_id: str,
        authorization_code_hash: str, device: EnrolledDevice,
    ) -> EnrolledDevice | None: ...
    async def get_device(self, tenant_id: str, device_id: str) -> EnrolledDevice | None: ...
    async def list_devices(
        self, tenant_id: str, owner_id: str
    ) -> list[EnrolledDevice]: ...
    # The ADMIN inventory read. ``list_devices`` hard-filters to the caller's own
    # owner_id in both implementations, so before this an administrator could not
    # answer "who has the desktop installed" at all - the ledger existed and had
    # no reader. Deliberately a separate method rather than a nullable owner_id:
    # an owner-scoped read that widens when a caller passes None is one missing
    # argument away from a disclosure.
    async def list_devices_for_tenant(
        self, tenant_id: str
    ) -> list[EnrolledDevice]: ...
    async def authenticate_device_session(
        self, tenant_id: str, device_id: str, token_hash: str
    ) -> EnrolledDevice | None: ...
    async def rotate_device_session(
        self, tenant_id: str, device_id: str, old_hash: str,
        new_hash: str, expires_at: datetime,
    ) -> bool: ...
    async def revoke_device(
        self, tenant_id: str, device_id: str, owner_id: str
    ) -> bool: ...
    async def create_device_root(self, root: DeviceRoot, owner_id: str) -> bool: ...
    async def list_device_roots(
        self, tenant_id: str, device_id: str
    ) -> list[DeviceRoot]: ...
    async def revoke_device_root(
        self, tenant_id: str, device_id: str, root_id: str, owner_id: str
    ) -> bool: ...
    async def create_device_lease(self, lease: DeviceLease) -> bool: ...
    async def get_device_lease(
        self, tenant_id: str, device_id: str, lease_id: str
    ) -> DeviceLease | None: ...
    async def list_pending_device_leases(
        self, tenant_id: str, device_id: str, limit: int = 50
    ) -> list[DeviceLease]: ...
    async def list_device_leases_for_owner(
        self, tenant_id: str, owner_id: str, device_id: str, limit: int = 50
    ) -> list[DeviceLease] | None: ...
    async def claim_device_lease(
        self, tenant_id: str, device_id: str, lease_id: str, signature: str,
        claim_token_hash: str, claim_expires_at: datetime,
    ) -> DeviceLease | None: ...
    async def settle_device_lease(
        self, tenant_id: str, device_id: str, lease_id: str,
        claim_token_hash: str, status: str, receipt: dict,
    ) -> bool: ...
