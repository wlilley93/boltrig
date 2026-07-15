"""Serialized trusted-authority state for the in-memory grant lease adapter."""

from __future__ import annotations

import asyncio
from datetime import datetime

from boltrig.fleet.domain.execution import PhaseAssignmentRef
from boltrig.fleet.domain.grant_lease import (
    GrantAuthoritySnapshot,
    GrantLeaseBinding,
    GrantLeaseConflict,
    GrantRootBinding,
    StaleGrantGeneration,
    StoredGrantLease,
    validate_revocation_reason,
)
from boltrig.fleet.infrastructure.memory_grant_lease_support import (
    aware,
    commit_revocations,
    expire_records,
    is_cancelled,
    require_authority_fence_capacity,
    require_authority_snapshot,
    require_binding,
    revocation_plan,
    state_fence_count,
)


class MemoryGrantAuthorityMixin:
    """Authority ledger seam sharing the lease store's serialization lock."""

    __slots__ = ()

    _cancelled_assignments: set[GrantLeaseBinding]
    _cancelled_roots: set[GrantRootBinding]
    _current_authority: dict[GrantLeaseBinding, GrantAuthoritySnapshot]
    _highest_authority_generation: dict[GrantLeaseBinding, int]
    _highest_lease_generation: dict[GrantLeaseBinding, int]
    _lock: asyncio.Lock
    _max_bindings: int
    _records: dict[str, StoredGrantLease]

    async def install_authority_snapshot(
        self,
        snapshot: GrantAuthoritySnapshot,
        *,
        now: datetime,
    ) -> None:
        """Test/local ledger seam; production resolves this state transactionally."""

        require_authority_snapshot(snapshot)
        current = aware("now", now)
        async with self._lock:
            expire_records(self._records, current)
            if is_cancelled(
                snapshot.binding,
                self._cancelled_assignments,
                self._cancelled_roots,
            ):
                raise StaleGrantGeneration("grant binding is terminally cancelled")
            previous = self._current_authority.get(snapshot.binding)
            if previous == snapshot:
                return
            highest = self._highest_authority_generation.get(snapshot.binding)
            if highest is not None and snapshot.authority_policy_generation <= highest:
                raise GrantLeaseConflict("authority replacement must advance the policy generation")
            require_authority_fence_capacity(
                snapshot.binding,
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
            replacements = revocation_plan(
                self._records,
                lambda record: record.binding == snapshot.binding,
                now=current,
                reason="authority_replaced",
            )
            commit_revocations(self._records, replacements)
            self._current_authority[snapshot.binding] = snapshot
            self._highest_authority_generation[snapshot.binding] = (
                snapshot.authority_policy_generation
            )

    async def suspend_grant_authority(
        self,
        binding: GrantLeaseBinding,
        *,
        now: datetime,
        reason: str = "authority_suspended",
    ) -> int:
        """Remove current approval/lifecycle authority and revoke active bearers."""

        require_binding(binding)
        current = aware("now", now)
        safe_reason = validate_revocation_reason(reason)
        async with self._lock:
            expire_records(self._records, current)
            replacements = revocation_plan(
                self._records,
                lambda record: record.binding == binding,
                now=current,
                reason=safe_reason,
            )
            commit_revocations(self._records, replacements)
            self._current_authority.pop(binding, None)
            return len(replacements)

    async def resolve_current_grant_authority(
        self,
        assignment: PhaseAssignmentRef,
        *,
        at: datetime,
    ) -> GrantAuthoritySnapshot | None:
        if type(assignment) is not PhaseAssignmentRef:
            raise TypeError("assignment must be an exact PhaseAssignmentRef")
        current = aware("at", at)
        binding = GrantLeaseBinding.from_assignment(assignment)
        async with self._lock:
            expire_records(self._records, current)
            if is_cancelled(
                binding,
                self._cancelled_assignments,
                self._cancelled_roots,
            ):
                return None
            return self._current_authority.get(binding)


__all__ = ["MemoryGrantAuthorityMixin"]
