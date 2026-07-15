"""Bounded atomic in-memory adapter for run-scoped grant leases."""

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
    validate_revocation_reason,
)

DEFAULT_MAX_GRANT_LEASE_RECORDS = 4_096
DEFAULT_MAX_GRANT_LEASE_BINDINGS = 2_048
HARD_MAX_GRANT_LEASE_STATE = 100_000


class GrantLeaseStoreCapacityExceeded(GrantLeaseConflict):
    """The bounded local adapter cannot retain another security tombstone."""


class MemoryGrantLeaseStore:
    """Async-serializable local adapter retaining generation fences until reset.

    Terminal records are security tombstones: silently evicting them could permit a
    generation replay or credential collision. The adapter therefore applies explicit
    bounded backpressure instead. Production retention must preserve equivalent fences.
    """

    __slots__ = (
        "_cancelled_assignments",
        "_cancelled_roots",
        "_highest_generation",
        "_lock",
        "_max_bindings",
        "_max_records",
        "_records",
    )

    def __init__(
        self,
        *,
        max_records: int = DEFAULT_MAX_GRANT_LEASE_RECORDS,
        max_bindings: int = DEFAULT_MAX_GRANT_LEASE_BINDINGS,
    ) -> None:
        self._max_records = _capacity("max_records", max_records)
        self._max_bindings = _capacity("max_bindings", max_bindings)
        self._records: dict[str, StoredGrantLease] = {}
        self._highest_generation: dict[GrantLeaseBinding, int] = {}
        self._cancelled_assignments: set[GrantLeaseBinding] = set()
        self._cancelled_roots: set[GrantRootBinding] = set()
        self._lock = asyncio.Lock()

    async def insert_active(self, lease: StoredGrantLease, *, now: datetime) -> None:
        """Atomically insert a fresh generation or reject without partial mutation."""

        if type(lease) is not StoredGrantLease:
            raise TypeError("lease must be an exact StoredGrantLease")
        _binding(lease.binding)
        current = _aware("now", now)
        if (
            lease.status is not GrantLeaseStatus.ACTIVE
            or lease.issued_at > current
            or not lease.is_active_at(
                current, policy_generation=lease.policy_generation
            )
        ):
            raise GrantLeaseConflict("lease is not active at insertion time")
        async with self._lock:
            self._expire(current)
            if self._is_cancelled(lease.binding):
                raise StaleGrantGeneration("grant binding is terminally cancelled")
            if self._credential_collision(lease):
                raise GrantLeaseConflict("lease identifier or digest was already inserted")
            highest = self._highest_generation.get(lease.binding)
            active = self._active_for(lease.binding)
            if any(item.policy_generation == lease.policy_generation for item in active):
                raise ActiveGrantGenerationConflict(
                    "generation already has an active lease"
                )
            if highest is not None and lease.policy_generation <= highest:
                raise StaleGrantGeneration(
                    "grant generation was already used or is older than durable history"
                )
            self._require_capacity(lease.binding, highest_generation=highest)
            superseded = tuple(
                (
                    item.lease_id,
                    item.revoke(at=current, reason="superseded_generation"),
                )
                for item in active
            )
            for lease_id, record in superseded:
                self._records[lease_id] = record
            self._records[lease.lease_id] = lease
            self._highest_generation[lease.binding] = lease.policy_generation

    async def find_active_by_digest(
        self,
        token_digest: str,
        binding: GrantLeaseBinding,
        *,
        now: datetime,
        policy_generation: int,
    ) -> StoredGrantLease | None:
        """Compare every retained digest before applying exact scope and generation."""

        current = _aware("now", now)
        _binding(binding)
        if not _digest_candidate(token_digest):
            return None
        async with self._lock:
            self._expire(current)
            matched: StoredGrantLease | None = None
            for record in self._records.values():
                if hmac.compare_digest(record.token_digest, token_digest):
                    matched = record
            if _matches(matched, binding, current, policy_generation):
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
        current = _aware("now", now)
        _binding(binding)
        if not isinstance(lease_id, str):
            return None
        async with self._lock:
            self._expire(current)
            record = self._records.get(lease_id)
            if _matches(record, binding, current, policy_generation):
                return record
            return None

    async def get_by_id(
        self, lease_id: str, binding: GrantLeaseBinding
    ) -> StoredGrantLease | None:
        _binding(binding)
        if not isinstance(lease_id, str):
            return None
        async with self._lock:
            record = self._records.get(lease_id)
            if record is None or record.binding != binding:
                return None
            return record

    async def revoke_exact(
        self,
        lease_id: str,
        binding: GrantLeaseBinding,
        *,
        now: datetime,
        reason: str,
    ) -> bool:
        current = _aware("now", now)
        _binding(binding)
        safe_reason = validate_revocation_reason(reason)
        async with self._lock:
            self._expire(current)
            record = self._records.get(lease_id)
            if (
                record is None
                or record.binding != binding
                or record.status is not GrantLeaseStatus.ACTIVE
            ):
                return False
            replacement = _revoke_record(record, now=current, reason=safe_reason)
            self._records[lease_id] = replacement
            return True

    async def revoke_assignment(
        self, binding: GrantLeaseBinding, *, now: datetime, reason: str
    ) -> int:
        current = _aware("now", now)
        _binding(binding)
        safe_reason = validate_revocation_reason(reason)
        async with self._lock:
            root = _root_binding_from_binding(binding)
            root_cancelled = root in self._cancelled_roots
            self._require_assignment_fence_capacity(binding, root_cancelled)
            self._expire(current)
            replacements = self._revocation_plan(
                lambda record: record.binding == binding,
                now=current,
                reason=safe_reason,
            )
            self._commit_revocations(replacements)
            if not root_cancelled:
                self._highest_generation.pop(binding, None)
                self._cancelled_assignments.add(binding)
            return len(replacements)

    async def revoke_root(
        self, binding: GrantRootBinding, *, now: datetime, reason: str
    ) -> int:
        current = _aware("now", now)
        if type(binding) is not GrantRootBinding:
            raise TypeError("binding must be an exact GrantRootBinding")
        safe_reason = validate_revocation_reason(reason)
        async with self._lock:
            self._require_root_fence_capacity(binding)
            self._expire(current)
            replacements = self._revocation_plan(
                lambda record: _root_binding(record) == binding,
                now=current,
                reason=safe_reason,
            )
            self._commit_revocations(replacements)
            self._cancelled_roots.add(binding)
            self._collapse_root_fences(binding)
            return len(replacements)

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

    def _credential_collision(self, lease: StoredGrantLease) -> bool:
        if lease.lease_id in self._records:
            return True
        return any(
            hmac.compare_digest(record.token_digest, lease.token_digest)
            for record in self._records.values()
        )

    def _require_capacity(
        self, binding: GrantLeaseBinding, *, highest_generation: int | None
    ) -> None:
        if len(self._records) >= self._max_records:
            raise GrantLeaseStoreCapacityExceeded("grant lease store capacity exceeded")
        if highest_generation is None and self._fence_count() >= self._max_bindings:
            raise GrantLeaseStoreCapacityExceeded("grant lease store capacity exceeded")

    def _require_assignment_fence_capacity(
        self, binding: GrantLeaseBinding, root_cancelled: bool
    ) -> None:
        if (
            not root_cancelled
            and binding not in self._cancelled_assignments
            and binding not in self._highest_generation
            and self._fence_count() >= self._max_bindings
        ):
            raise GrantLeaseStoreCapacityExceeded("grant lease store capacity exceeded")

    def _require_root_fence_capacity(self, root: GrantRootBinding) -> None:
        if root in self._cancelled_roots:
            return
        collapsed = sum(
            _root_binding_from_binding(binding) == root
            for binding in (*self._highest_generation, *self._cancelled_assignments)
        )
        if self._fence_count() - collapsed >= self._max_bindings:
            raise GrantLeaseStoreCapacityExceeded("grant lease store capacity exceeded")

    def _fence_count(self) -> int:
        return (
            len(self._highest_generation)
            + len(self._cancelled_assignments)
            + len(self._cancelled_roots)
        )

    def _is_cancelled(self, binding: GrantLeaseBinding) -> bool:
        return binding in self._cancelled_assignments or (
            _root_binding_from_binding(binding) in self._cancelled_roots
        )

    def _collapse_root_fences(self, root: GrantRootBinding) -> None:
        self._highest_generation = {
            binding: generation
            for binding, generation in self._highest_generation.items()
            if _root_binding_from_binding(binding) != root
        }
        self._cancelled_assignments = {
            binding
            for binding in self._cancelled_assignments
            if _root_binding_from_binding(binding) != root
        }

    def _revocation_plan(
        self,
        predicate: Callable[[StoredGrantLease], bool],
        *,
        now: datetime,
        reason: str,
    ) -> tuple[tuple[str, StoredGrantLease], ...]:
        return tuple(
            (lease_id, _revoke_record(record, now=now, reason=reason))
            for lease_id, record in self._records.items()
            if predicate(record) and record.status is GrantLeaseStatus.ACTIVE
        )

    def _commit_revocations(
        self, replacements: tuple[tuple[str, StoredGrantLease], ...]
    ) -> None:
        for lease_id, record in replacements:
            self._records[lease_id] = record


def _capacity(label: str, value: int) -> int:
    if type(value) is not int or not 1 <= value <= HARD_MAX_GRANT_LEASE_STATE:
        raise ValueError(
            f"{label} must be between 1 and {HARD_MAX_GRANT_LEASE_STATE}"
        )
    return value


def _aware(label: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value


def _binding(value: GrantLeaseBinding) -> None:
    if type(value) is not GrantLeaseBinding:
        raise TypeError("binding must be an exact GrantLeaseBinding")


def _digest_candidate(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64 or value != value.lower():
        return False
    try:
        bytes.fromhex(value)
    except ValueError:
        return False
    return True


def _matches(
    record: StoredGrantLease | None,
    binding: GrantLeaseBinding,
    now: datetime,
    policy_generation: int,
) -> bool:
    return bool(
        record is not None
        and record.binding == binding
        and record.issued_at <= now
        and record.is_active_at(now, policy_generation=policy_generation)
    )


def _root_binding(record: StoredGrantLease) -> GrantRootBinding:
    return _root_binding_from_binding(record.binding)


def _root_binding_from_binding(binding: GrantLeaseBinding) -> GrantRootBinding:
    return GrantRootBinding(binding.tenant_id, binding.workspace_id, binding.root_run_id)


def _revoke_record(
    record: StoredGrantLease, *, now: datetime, reason: str
) -> StoredGrantLease:
    revoked_at = max(now, record.issued_at)
    return record.revoke(at=revoked_at, reason=reason)


__all__ = [
    "DEFAULT_MAX_GRANT_LEASE_BINDINGS",
    "DEFAULT_MAX_GRANT_LEASE_RECORDS",
    "GrantLeaseStoreCapacityExceeded",
    "HARD_MAX_GRANT_LEASE_STATE",
    "MemoryGrantLeaseStore",
]
