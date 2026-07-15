"""Atomic persistence port for run-scoped MCP grant leases."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from boltrig.fleet.domain.grant_lease import (
    GrantLeaseBinding,
    GrantRootBinding,
    StoredGrantLease,
)


class GrantLeaseStore(Protocol):
    """Durable atomic operations; implementations must never persist raw bearers."""

    async def insert_active(self, lease: StoredGrantLease, *, now: datetime) -> None:
        """Insert once, enforcing one active lease and monotonic generation per binding."""
        ...

    async def find_active_by_digest(
        self,
        token_digest: str,
        binding: GrantLeaseBinding,
        *,
        now: datetime,
        policy_generation: int,
    ) -> StoredGrantLease | None:
        """Compare the digest in constant time and exact scope atomically, then expire."""
        ...

    async def find_active_by_id(
        self,
        lease_id: str,
        binding: GrantLeaseBinding,
        *,
        now: datetime,
        policy_generation: int,
    ) -> StoredGrantLease | None: ...

    async def get_by_id(self, lease_id: str) -> StoredGrantLease | None: ...

    async def revoke_exact(
        self,
        lease_id: str,
        binding: GrantLeaseBinding,
        *,
        now: datetime,
        reason: str,
    ) -> bool: ...

    async def revoke_assignment(
        self, binding: GrantLeaseBinding, *, now: datetime, reason: str
    ) -> int: ...

    async def revoke_root(
        self, binding: GrantRootBinding, *, now: datetime, reason: str
    ) -> int: ...


__all__ = ["GrantLeaseStore"]
