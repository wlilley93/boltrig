"""Bounded atomic in-memory adapter for run-scoped grant leases."""

from __future__ import annotations

import asyncio
import hmac
from datetime import datetime

from boltrig.fleet.domain.grant_lease import (
    GrantAuthoritySnapshot,
    GrantLeaseBinding,
    GrantLeaseCandidate,
    GrantLeaseConflict,
    GrantLeaseStatus,
    GrantRootBinding,
    LeaseGenerationExhausted,
    StaleGrantGeneration,
    StoredGrantLease,
    validate_revocation_reason,
)
from boltrig.fleet.infrastructure.memory_grant_authority import (
    MemoryGrantAuthorityMixin,
)
from boltrig.fleet.infrastructure.memory_grant_lease_support import (
    DEFAULT_MAX_GRANT_LEASE_BINDINGS,
    DEFAULT_MAX_GRANT_LEASE_RECORDS,
    HARD_MAX_GRANT_LEASE_STATE,
    MAX_SIGNED_BIGINT,
    GrantLeaseStoreCapacityExceeded,
    IssueOperationKey,
    active_for,
    aware as _aware,
    capacity as _capacity,
    commit_revocations,
    expire_records,
    is_cancelled,
    is_digest_candidate as _digest_candidate,
    matches as _matches,
    operation_key as _operation_key,
    require_assignment_fence_capacity,
    require_authority_snapshot as _authority_snapshot,
    require_binding as _binding,
    require_capacity,
    require_root_fence_capacity,
    revocation_plan,
    revoke_record as _revoke_record,
    root_binding as _root_binding,
    root_binding_from_binding as _root_binding_from_binding,
    state_fence_count,
)


class MemoryGrantLeaseStore(MemoryGrantAuthorityMixin):
    """Async-serializable local adapter retaining generation fences until reset.

    Terminal records are security tombstones: silently evicting them could permit a
    generation replay or credential collision. The adapter therefore applies explicit
    bounded backpressure instead. Production retention must preserve equivalent fences.
    """

    __slots__ = (
        "_cancelled_assignments",
        "_cancelled_roots",
        "_current_authority",
        "_highest_authority_generation",
        "_highest_lease_generation",
        "_issue_operation_receipts",
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
        self._highest_lease_generation: dict[GrantLeaseBinding, int] = {}
        self._highest_authority_generation: dict[GrantLeaseBinding, int] = {}
        self._current_authority: dict[GrantLeaseBinding, GrantAuthoritySnapshot] = {}
        self._issue_operation_receipts: dict[IssueOperationKey, str] = {}
        self._cancelled_assignments: set[GrantLeaseBinding] = set()
        self._cancelled_roots: set[GrantRootBinding] = set()
        self._lock = asyncio.Lock()

    async def insert_active(
        self,
        candidate: GrantLeaseCandidate,
        *,
        expected_authority: GrantAuthoritySnapshot,
        now: datetime,
    ) -> StoredGrantLease:
        """Idempotently compare-and-swap and allocate the next lease generation."""

        if type(candidate) is not GrantLeaseCandidate:
            raise TypeError("candidate must be an exact GrantLeaseCandidate")
        _authority_snapshot(expected_authority)
        _binding(candidate.binding)
        current = _aware("now", now)
        async with self._lock:
            expire_records(self._records, current)
            receipt = self._operation_receipt(candidate)
            if receipt is not None:
                if receipt.is_projection_of(candidate):
                    return receipt
                raise GrantLeaseConflict("issue operation conflicts with durable receipt")
            if candidate.issued_at > current or candidate.expires_at <= current:
                raise GrantLeaseConflict("lease is not active at insertion time")
            if is_cancelled(
                candidate.binding,
                self._cancelled_assignments,
                self._cancelled_roots,
            ):
                raise StaleGrantGeneration("grant binding is terminally cancelled")
            self._require_current_authority(candidate, expected_authority)
            if self._credential_collision(candidate):
                raise GrantLeaseConflict("lease identifier or digest was already inserted")
            highest = self._highest_lease_generation.get(candidate.binding)
            if candidate.expected_current_lease_generation != highest:
                raise StaleGrantGeneration("lease generation compare-and-swap failed")
            if highest == MAX_SIGNED_BIGINT:
                raise LeaseGenerationExhausted("lease generation fence is exhausted")
            require_capacity(
                record_count=len(self._records),
                max_records=self._max_records,
                binding=candidate.binding,
                highest_generations=self._highest_lease_generation,
                highest_authority_generations=self._highest_authority_generation,
                cancelled_assignments=self._cancelled_assignments,
                cancelled_roots=self._cancelled_roots,
                fence_count=state_fence_count(
                    self._highest_lease_generation,
                    self._highest_authority_generation,
                    self._cancelled_assignments,
                    self._cancelled_roots,
                ),
                max_bindings=self._max_bindings,
            )
            lease_generation = 1 if highest is None else highest + 1
            stored = StoredGrantLease.from_candidate(
                candidate,
                lease_generation=lease_generation,
            )
            active = active_for(self._records, candidate.binding)
            superseded = tuple(
                (
                    item.lease_id,
                    item.revoke(at=current, reason="superseded_generation"),
                )
                for item in active
            )
            for lease_id, record in superseded:
                self._records[lease_id] = record
            self._records[stored.lease_id] = stored
            self._highest_lease_generation[stored.binding] = stored.lease_generation
            self._issue_operation_receipts[_operation_key(candidate)] = stored.lease_id
            return stored

    async def get_by_issue_operation_id(
        self,
        issue_operation_id: str,
        binding: GrantLeaseBinding,
    ) -> StoredGrantLease | None:
        _binding(binding)
        if type(issue_operation_id) is not str or not issue_operation_id:
            return None
        key = (binding.tenant_id, binding.workspace_id, issue_operation_id)
        async with self._lock:
            lease_id = self._issue_operation_receipts.get(key)
            if lease_id is None:
                return None
            record = self._records.get(lease_id)
            if record is None or record.binding != binding:
                return None
            return record

    async def find_active_by_digest(
        self,
        token_digest: str,
        binding: GrantLeaseBinding,
        *,
        now: datetime,
        expected_authority: GrantAuthoritySnapshot,
    ) -> StoredGrantLease | None:
        """Compare every retained digest before applying exact scope and generation."""

        current = _aware("now", now)
        _binding(binding)
        _authority_snapshot(expected_authority)
        if expected_authority.binding != binding:
            return None
        if not _digest_candidate(token_digest):
            return None
        async with self._lock:
            expire_records(self._records, current)
            matched: StoredGrantLease | None = None
            for record in self._records.values():
                if hmac.compare_digest(record.token_digest, token_digest):
                    matched = record
            if self._current_authority.get(binding) != expected_authority:
                return None
            if _matches(matched, binding, current, expected_authority):
                return matched
            return None

    async def find_active_by_id(
        self,
        lease_id: str,
        binding: GrantLeaseBinding,
        *,
        now: datetime,
        expected_authority: GrantAuthoritySnapshot,
    ) -> StoredGrantLease | None:
        current = _aware("now", now)
        _binding(binding)
        _authority_snapshot(expected_authority)
        if expected_authority.binding != binding:
            return None
        if not isinstance(lease_id, str):
            return None
        async with self._lock:
            expire_records(self._records, current)
            record = self._records.get(lease_id)
            if self._current_authority.get(binding) != expected_authority:
                return None
            if _matches(record, binding, current, expected_authority):
                return record
            return None

    async def get_by_id(self, lease_id: str, binding: GrantLeaseBinding) -> StoredGrantLease | None:
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
            expire_records(self._records, current)
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
            require_assignment_fence_capacity(
                binding,
                root_cancelled=root_cancelled,
                cancelled_assignments=self._cancelled_assignments,
                highest_generations=self._highest_lease_generation,
                highest_authority_generations=self._highest_authority_generation,
                fence_count=state_fence_count(
                    self._highest_lease_generation,
                    self._highest_authority_generation,
                    self._cancelled_assignments,
                    self._cancelled_roots,
                ),
                max_bindings=self._max_bindings,
            )
            expire_records(self._records, current)
            replacements = revocation_plan(
                self._records,
                lambda record: record.binding == binding,
                now=current,
                reason=safe_reason,
            )
            commit_revocations(self._records, replacements)
            if not root_cancelled:
                self._highest_lease_generation.pop(binding, None)
                self._highest_authority_generation.pop(binding, None)
                self._current_authority.pop(binding, None)
                self._cancelled_assignments.add(binding)
            return len(replacements)

    async def revoke_root(self, binding: GrantRootBinding, *, now: datetime, reason: str) -> int:
        current = _aware("now", now)
        if type(binding) is not GrantRootBinding:
            raise TypeError("binding must be an exact GrantRootBinding")
        safe_reason = validate_revocation_reason(reason)
        async with self._lock:
            require_root_fence_capacity(
                binding,
                cancelled_roots=self._cancelled_roots,
                cancelled_assignments=self._cancelled_assignments,
                highest_generations=self._highest_lease_generation,
                highest_authority_generations=self._highest_authority_generation,
                fence_count=state_fence_count(
                    self._highest_lease_generation,
                    self._highest_authority_generation,
                    self._cancelled_assignments,
                    self._cancelled_roots,
                ),
                max_bindings=self._max_bindings,
            )
            expire_records(self._records, current)
            replacements = revocation_plan(
                self._records,
                lambda record: _root_binding(record) == binding,
                now=current,
                reason=safe_reason,
            )
            commit_revocations(self._records, replacements)
            self._cancelled_roots.add(binding)
            self._collapse_root_fences(binding)
            return len(replacements)

    def _credential_collision(self, candidate: GrantLeaseCandidate) -> bool:
        if candidate.lease_id in self._records:
            return True
        return any(
            hmac.compare_digest(record.token_digest, candidate.token_digest)
            for record in self._records.values()
        )

    def _require_current_authority(
        self,
        candidate: GrantLeaseCandidate,
        expected_authority: GrantAuthoritySnapshot,
    ) -> None:
        if (
            candidate.binding != expected_authority.binding
            or not candidate.matches_authority_snapshot(expected_authority)
            or self._current_authority.get(candidate.binding) != expected_authority
        ):
            raise GrantLeaseConflict("grant authority differs from the current durable snapshot")

    def _operation_receipt(self, candidate: GrantLeaseCandidate) -> StoredGrantLease | None:
        lease_id = self._issue_operation_receipts.get(_operation_key(candidate))
        if lease_id is None:
            return None
        record = self._records.get(lease_id)
        if record is None:
            raise GrantLeaseConflict("issue operation receipt is incomplete")
        return record

    def _collapse_root_fences(self, root: GrantRootBinding) -> None:
        self._highest_lease_generation = {
            binding: generation
            for binding, generation in self._highest_lease_generation.items()
            if _root_binding_from_binding(binding) != root
        }
        self._current_authority = {
            binding: snapshot
            for binding, snapshot in self._current_authority.items()
            if _root_binding_from_binding(binding) != root
        }
        self._highest_authority_generation = {
            binding: generation
            for binding, generation in self._highest_authority_generation.items()
            if _root_binding_from_binding(binding) != root
        }
        self._cancelled_assignments = {
            binding
            for binding in self._cancelled_assignments
            if _root_binding_from_binding(binding) != root
        }


__all__ = [
    "DEFAULT_MAX_GRANT_LEASE_BINDINGS",
    "DEFAULT_MAX_GRANT_LEASE_RECORDS",
    "GrantLeaseStoreCapacityExceeded",
    "HARD_MAX_GRANT_LEASE_STATE",
    "MemoryGrantLeaseStore",
]
