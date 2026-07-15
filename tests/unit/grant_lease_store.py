"""Atomic in-memory GrantLeaseStore used by grant-lease contract tests."""

from __future__ import annotations

import asyncio
import hmac
from collections.abc import Callable
from datetime import datetime

from boltrig.fleet.domain.grant_lease import (
    ActiveGrantGenerationConflict,
    GrantLeaseBinding,
    GrantLeaseConflict,
    GrantLeaseStatus,
    GrantRootBinding,
    StaleGrantGeneration,
    StoredGrantLease,
)


class MemoryGrantLeaseStore:
    """Strict atomic fake mirroring the future Postgres transaction contract."""

    def __init__(self) -> None:
        self._records: dict[str, StoredGrantLease] = {}
        self._lock = asyncio.Lock()

    def snapshot(self) -> tuple[StoredGrantLease, ...]:
        return tuple(sorted(self._records.values(), key=lambda item: item.lease_id))

    def _expire(self, now: datetime) -> None:
        for lease_id, record in tuple(self._records.items()):
            if record.status is GrantLeaseStatus.ACTIVE and record.expires_at <= now:
                self._records[lease_id] = record.expire()

    def _active_for(self, binding: GrantLeaseBinding) -> tuple[StoredGrantLease, ...]:
        return tuple(
            record
            for record in self._records.values()
            if record.binding == binding and record.status is GrantLeaseStatus.ACTIVE
        )

    async def insert_active(self, lease: StoredGrantLease, *, now: datetime) -> None:
        async with self._lock:
            self._expire(now)
            if lease.lease_id in self._records or any(
                hmac.compare_digest(record.token_digest, lease.token_digest)
                for record in self._records.values()
            ):
                raise GrantLeaseConflict("lease identifier or digest was already inserted")
            history = tuple(
                record for record in self._records.values() if record.binding == lease.binding
            )
            highest = max((record.policy_generation for record in history), default=0)
            active = self._active_for(lease.binding)
            if any(record.policy_generation == lease.policy_generation for record in active):
                raise ActiveGrantGenerationConflict("generation already has an active lease")
            if history and lease.policy_generation <= highest:
                raise StaleGrantGeneration(
                    "grant generation was already used or is older than durable history"
                )
            for record in active:
                self._records[record.lease_id] = record.revoke(
                    at=now, reason="superseded_generation"
                )
            self._records[lease.lease_id] = lease

    async def find_active_by_digest(
        self,
        token_digest: str,
        binding: GrantLeaseBinding,
        *,
        now: datetime,
        policy_generation: int,
    ) -> StoredGrantLease | None:
        async with self._lock:
            self._expire(now)
            matched: StoredGrantLease | None = None
            for record in self._records.values():
                if hmac.compare_digest(record.token_digest, token_digest):
                    matched = record
            if (
                matched is not None
                and matched.binding == binding
                and matched.is_active_at(now, policy_generation=policy_generation)
            ):
                return matched
            return None

    async def find_active_by_id(
        self,
        lease_id: str,
        binding: GrantLeaseBinding,
        *,
        now: datetime,
        policy_generation: int,
    ) -> StoredGrantLease | None:
        async with self._lock:
            self._expire(now)
            record = self._records.get(lease_id)
            if (
                record is not None
                and record.binding == binding
                and record.is_active_at(now, policy_generation=policy_generation)
            ):
                return record
            return None

    async def get_by_id(self, lease_id: str) -> StoredGrantLease | None:
        async with self._lock:
            return self._records.get(lease_id)

    async def revoke_exact(
        self,
        lease_id: str,
        binding: GrantLeaseBinding,
        *,
        now: datetime,
        reason: str,
    ) -> bool:
        async with self._lock:
            self._expire(now)
            record = self._records.get(lease_id)
            if record is None or record.binding != binding:
                return False
            if record.status is not GrantLeaseStatus.ACTIVE:
                return False
            self._records[lease_id] = record.revoke(at=now, reason=reason)
            return True

    async def revoke_assignment(
        self, binding: GrantLeaseBinding, *, now: datetime, reason: str
    ) -> int:
        async with self._lock:
            self._expire(now)
            return self._revoke_matching(
                lambda record: record.binding == binding, now=now, reason=reason
            )

    async def revoke_root(
        self, binding: GrantRootBinding, *, now: datetime, reason: str
    ) -> int:
        async with self._lock:
            self._expire(now)
            return self._revoke_matching(
                lambda record: GrantRootBinding(
                    record.binding.tenant_id,
                    record.binding.workspace_id,
                    record.binding.root_run_id,
                )
                == binding,
                now=now,
                reason=reason,
            )

    def _revoke_matching(
        self,
        predicate: Callable[[StoredGrantLease], bool],
        *,
        now: datetime,
        reason: str,
    ) -> int:
        matches = 0
        for lease_id, record in tuple(self._records.items()):
            if predicate(record) and record.status is GrantLeaseStatus.ACTIVE:
                self._records[lease_id] = record.revoke(at=now, reason=reason)
                matches += 1
        return matches


__all__ = ["MemoryGrantLeaseStore"]
