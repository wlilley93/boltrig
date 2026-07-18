"""Pure bounded-state helpers for the in-memory grant lease adapter."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TypeAlias

from boltrig.fleet.domain.grant_lease import (
    GrantAuthoritySnapshot,
    GrantLeaseBinding,
    GrantLeaseCandidate,
    GrantLeaseConflict,
    GrantLeaseStatus,
    GrantRootBinding,
    StoredGrantLease,
)

DEFAULT_MAX_GRANT_LEASE_RECORDS = 4_096
DEFAULT_MAX_GRANT_LEASE_BINDINGS = 2_048
HARD_MAX_GRANT_LEASE_STATE = 100_000
MAX_SIGNED_BIGINT = 2**63 - 1

IssueOperationKey: TypeAlias = tuple[str, str, str]


class GrantLeaseStoreCapacityExceeded(GrantLeaseConflict):
    """The bounded local adapter cannot retain another security tombstone."""


def capacity(label: str, value: int) -> int:
    if type(value) is not int or not 1 <= value <= HARD_MAX_GRANT_LEASE_STATE:
        raise ValueError(f"{label} must be between 1 and {HARD_MAX_GRANT_LEASE_STATE}")
    return value


def aware(label: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value


def require_binding(value: GrantLeaseBinding) -> None:
    if type(value) is not GrantLeaseBinding:
        raise TypeError("binding must be an exact GrantLeaseBinding")


def require_authority_snapshot(value: GrantAuthoritySnapshot) -> None:
    if type(value) is not GrantAuthoritySnapshot:
        raise TypeError("expected_authority must be an exact GrantAuthoritySnapshot")


def is_digest_candidate(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64 or value != value.lower():
        return False
    try:
        bytes.fromhex(value)
    except ValueError:
        return False
    return True


def matches(
    record: StoredGrantLease | None,
    binding: GrantLeaseBinding,
    now: datetime,
    expected_authority: GrantAuthoritySnapshot,
) -> bool:
    return bool(
        record is not None
        and record.binding == binding
        and record.issued_at <= now
        and record.authority_snapshot == expected_authority
        and record.is_active_at(
            now,
            authority_policy_generation=expected_authority.authority_policy_generation,
        )
    )


def operation_key(candidate: GrantLeaseCandidate) -> IssueOperationKey:
    return (
        candidate.binding.tenant_id,
        candidate.binding.workspace_id,
        candidate.issue_operation_id,
    )


def root_binding(record: StoredGrantLease) -> GrantRootBinding:
    return root_binding_from_binding(record.binding)


def root_binding_from_binding(binding: GrantLeaseBinding) -> GrantRootBinding:
    return GrantRootBinding(binding.tenant_id, binding.workspace_id, binding.root_run_id)


def revoke_record(
    record: StoredGrantLease,
    *,
    now: datetime,
    reason: str,
) -> StoredGrantLease:
    return record.revoke(at=max(now, record.issued_at), reason=reason)


def expire_records(records: dict[str, StoredGrantLease], now: datetime) -> None:
    for lease_id, record in tuple(records.items()):
        if record.status is GrantLeaseStatus.ACTIVE and record.expires_at <= now:
            records[lease_id] = record.expire()


def active_for(
    records: dict[str, StoredGrantLease],
    binding: GrantLeaseBinding,
) -> tuple[StoredGrantLease, ...]:
    return tuple(
        record
        for record in records.values()
        if record.binding == binding and record.status is GrantLeaseStatus.ACTIVE
    )


def revocation_plan(
    records: dict[str, StoredGrantLease],
    predicate: Callable[[StoredGrantLease], bool],
    *,
    now: datetime,
    reason: str,
) -> tuple[tuple[str, StoredGrantLease], ...]:
    return tuple(
        (lease_id, revoke_record(record, now=now, reason=reason))
        for lease_id, record in records.items()
        if predicate(record) and record.status is GrantLeaseStatus.ACTIVE
    )


def commit_revocations(
    records: dict[str, StoredGrantLease],
    replacements: tuple[tuple[str, StoredGrantLease], ...],
) -> None:
    for lease_id, record in replacements:
        records[lease_id] = record


def state_fence_count(
    highest_generations: dict[GrantLeaseBinding, int],
    highest_authority_generations: dict[GrantLeaseBinding, int],
    cancelled_assignments: set[GrantLeaseBinding],
    cancelled_roots: set[GrantRootBinding],
) -> int:
    binding_fences = (
        set(highest_generations)
        | set(highest_authority_generations)
        | cancelled_assignments
    )
    return len(binding_fences) + len(cancelled_roots)


def binding_has_fence(
    binding: GrantLeaseBinding,
    *,
    highest_generations: dict[GrantLeaseBinding, int],
    highest_authority_generations: dict[GrantLeaseBinding, int],
    cancelled_assignments: set[GrantLeaseBinding],
    cancelled_roots: set[GrantRootBinding],
) -> bool:
    return bool(
        binding in highest_generations
        or binding in highest_authority_generations
        or binding in cancelled_assignments
        or root_binding_from_binding(binding) in cancelled_roots
    )


def require_capacity(
    *,
    record_count: int,
    max_records: int,
    binding: GrantLeaseBinding,
    highest_generations: dict[GrantLeaseBinding, int],
    highest_authority_generations: dict[GrantLeaseBinding, int],
    cancelled_assignments: set[GrantLeaseBinding],
    cancelled_roots: set[GrantRootBinding],
    fence_count: int,
    max_bindings: int,
) -> None:
    adds_fence = not binding_has_fence(
        binding,
        highest_generations=highest_generations,
        highest_authority_generations=highest_authority_generations,
        cancelled_assignments=cancelled_assignments,
        cancelled_roots=cancelled_roots,
    )
    if record_count >= max_records or (adds_fence and fence_count >= max_bindings):
        raise GrantLeaseStoreCapacityExceeded("grant lease store capacity exceeded")


def require_authority_fence_capacity(
    binding: GrantLeaseBinding,
    *,
    highest_generations: dict[GrantLeaseBinding, int],
    highest_authority_generations: dict[GrantLeaseBinding, int],
    cancelled_assignments: set[GrantLeaseBinding],
    cancelled_roots: set[GrantRootBinding],
    fence_count: int,
    max_bindings: int,
) -> None:
    if not binding_has_fence(
        binding,
        highest_generations=highest_generations,
        highest_authority_generations=highest_authority_generations,
        cancelled_assignments=cancelled_assignments,
        cancelled_roots=cancelled_roots,
    ) and fence_count >= max_bindings:
        raise GrantLeaseStoreCapacityExceeded("grant lease store capacity exceeded")


def require_assignment_fence_capacity(
    binding: GrantLeaseBinding,
    *,
    root_cancelled: bool,
    cancelled_assignments: set[GrantLeaseBinding],
    highest_generations: dict[GrantLeaseBinding, int],
    highest_authority_generations: dict[GrantLeaseBinding, int],
    fence_count: int,
    max_bindings: int,
) -> None:
    if (
        not root_cancelled
        and binding not in cancelled_assignments
        and binding not in highest_generations
        and binding not in highest_authority_generations
        and fence_count >= max_bindings
    ):
        raise GrantLeaseStoreCapacityExceeded("grant lease store capacity exceeded")


def require_root_fence_capacity(
    root: GrantRootBinding,
    *,
    cancelled_roots: set[GrantRootBinding],
    cancelled_assignments: set[GrantLeaseBinding],
    highest_generations: dict[GrantLeaseBinding, int],
    highest_authority_generations: dict[GrantLeaseBinding, int],
    fence_count: int,
    max_bindings: int,
) -> None:
    if root in cancelled_roots:
        return
    child_bindings = (
        set(highest_generations)
        | set(highest_authority_generations)
        | cancelled_assignments
    )
    collapsed = sum(
        root_binding_from_binding(binding) == root for binding in child_bindings
    )
    if fence_count - collapsed >= max_bindings:
        raise GrantLeaseStoreCapacityExceeded("grant lease store capacity exceeded")


def is_cancelled(
    binding: GrantLeaseBinding,
    cancelled_assignments: set[GrantLeaseBinding],
    cancelled_roots: set[GrantRootBinding],
) -> bool:
    return binding in cancelled_assignments or (
        root_binding_from_binding(binding) in cancelled_roots
    )


__all__ = [
    "DEFAULT_MAX_GRANT_LEASE_BINDINGS",
    "DEFAULT_MAX_GRANT_LEASE_RECORDS",
    "GrantLeaseStoreCapacityExceeded",
    "HARD_MAX_GRANT_LEASE_STATE",
    "IssueOperationKey",
    "MAX_SIGNED_BIGINT",
    "active_for",
    "aware",
    "binding_has_fence",
    "capacity",
    "commit_revocations",
    "expire_records",
    "is_cancelled",
    "is_digest_candidate",
    "matches",
    "operation_key",
    "require_assignment_fence_capacity",
    "require_authority_fence_capacity",
    "require_authority_snapshot",
    "require_binding",
    "require_capacity",
    "require_root_fence_capacity",
    "revocation_plan",
    "revoke_record",
    "root_binding",
    "root_binding_from_binding",
    "state_fence_count",
]
