"""Test-only compatibility surface over the production in-memory adapter."""

from boltrig.fleet.domain.grant_lease import StoredGrantLease
from boltrig.fleet.infrastructure.memory_grant_leases import (
    MemoryGrantLeaseStore as ProductionMemoryGrantLeaseStore,
)


class MemoryGrantLeaseStore(ProductionMemoryGrantLeaseStore):
    """Preserve legacy snapshot assertions without duplicating store semantics."""

    __slots__ = ()

    def snapshot(self) -> tuple[StoredGrantLease, ...]:
        return tuple(sorted(self._records.values(), key=lambda item: item.lease_id))


__all__ = ["MemoryGrantLeaseStore"]
