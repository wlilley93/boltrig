"""Atomic persistence port for run-scoped MCP grant leases."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from boltrig.fleet.domain.grant_lease import (
    GrantAuthoritySnapshot,
    GrantLeaseCandidate,
    GrantLeaseBinding,
    GrantRootBinding,
    StoredGrantLease,
)


class GrantLeaseStore(Protocol):
    """Durable atomic operations; implementations must never persist raw bearers.

    ``expected_authority`` is a compare value, never an authority source. Inserts and
    active lookups must recheck it against the current durable assignment, approval,
    lifecycle, and authority evaluation in the same serialization boundary.
    """

    async def insert_active(
        self,
        candidate: GrantLeaseCandidate,
        *,
        expected_authority: GrantAuthoritySnapshot,
        now: datetime,
    ) -> StoredGrantLease:
        """Idempotently compare-and-swap and allocate the next lease generation."""
        ...

    async def get_by_issue_operation_id(
        self,
        issue_operation_id: str,
        binding: GrantLeaseBinding,
    ) -> StoredGrantLease | None:
        """Read a durable issue receipt only through its exact assignment scope."""
        ...

    async def find_active_by_digest(
        self,
        token_digest: str,
        binding: GrantLeaseBinding,
        *,
        now: datetime,
        expected_authority: GrantAuthoritySnapshot,
    ) -> StoredGrantLease | None:
        """Compare the digest in constant time and exact scope atomically, then expire."""
        ...

    async def find_active_by_id(
        self,
        lease_id: str,
        binding: GrantLeaseBinding,
        *,
        now: datetime,
        expected_authority: GrantAuthoritySnapshot,
    ) -> StoredGrantLease | None: ...

    async def get_by_id(self, lease_id: str, binding: GrantLeaseBinding) -> StoredGrantLease | None:
        """Read metadata only through the lease's exact assignment scope."""
        ...

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
