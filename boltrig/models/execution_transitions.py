"""Canonical storage lifecycle vocabulary and legal transition matrices."""

from __future__ import annotations

from enum import Enum
from typing import cast

from .execution_scope import _require_exact_enum


class PhaseMode(str, Enum):
    """Storage vocabulary matching the fleet runtime phase-mode values."""

    READ_ONLY = "read_only"
    APPROVAL_GATED_WRITE = "approval_gated_write"


class RootRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    CANCELLING = "cancelling"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionPhaseStatus(str, Enum):
    """Fleet-aligned values plus VERIFYING, projected explicitly as RUNNING."""

    PENDING = "pending"
    STARTING = "starting"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    INTERRUPTING = "interrupting"
    VERIFYING = "verifying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class LedgerWorkItemStatus(str, Enum):
    """Values intentionally align with the existing WorkStatus vocabulary."""

    PENDING = "pending"
    BLOCKED = "blocked"
    IN_FLIGHT = "in_flight"
    AWAITING_HUMAN = "awaiting_human"
    VERIFYING = "verifying"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AssignmentStatus(str, Enum):
    OFFERED = "offered"
    CLAIMED = "claimed"
    RUNNING = "running"
    RELEASED = "released"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class ResultStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class VerificationStatus(str, Enum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    NEEDS_REVISION = "needs_revision"


ROOT_RUN_TRANSITIONS: dict[RootRunStatus, frozenset[RootRunStatus]] = {
    RootRunStatus.PENDING: frozenset({RootRunStatus.RUNNING, RootRunStatus.CANCELLED}),
    RootRunStatus.RUNNING: frozenset(
        {RootRunStatus.CANCELLING, RootRunStatus.SUCCEEDED, RootRunStatus.FAILED}
    ),
    RootRunStatus.CANCELLING: frozenset({RootRunStatus.CANCELLED, RootRunStatus.FAILED}),
    RootRunStatus.SUCCEEDED: frozenset(),
    RootRunStatus.FAILED: frozenset(),
    RootRunStatus.CANCELLED: frozenset(),
}

PHASE_TRANSITIONS: dict[ExecutionPhaseStatus, frozenset[ExecutionPhaseStatus]] = {
    ExecutionPhaseStatus.PENDING: frozenset(
        {ExecutionPhaseStatus.STARTING, ExecutionPhaseStatus.INTERRUPTED}
    ),
    ExecutionPhaseStatus.STARTING: frozenset(
        {
            ExecutionPhaseStatus.RUNNING,
            ExecutionPhaseStatus.FAILED,
            ExecutionPhaseStatus.INTERRUPTING,
        }
    ),
    ExecutionPhaseStatus.RUNNING: frozenset(
        {
            ExecutionPhaseStatus.AWAITING_APPROVAL,
            ExecutionPhaseStatus.INTERRUPTING,
            ExecutionPhaseStatus.VERIFYING,
            ExecutionPhaseStatus.SUCCEEDED,
            ExecutionPhaseStatus.FAILED,
        }
    ),
    ExecutionPhaseStatus.AWAITING_APPROVAL: frozenset(
        {
            ExecutionPhaseStatus.RUNNING,
            ExecutionPhaseStatus.INTERRUPTING,
            ExecutionPhaseStatus.FAILED,
        }
    ),
    ExecutionPhaseStatus.INTERRUPTING: frozenset(
        {ExecutionPhaseStatus.INTERRUPTED, ExecutionPhaseStatus.FAILED}
    ),
    ExecutionPhaseStatus.VERIFYING: frozenset(
        {
            ExecutionPhaseStatus.RUNNING,
            ExecutionPhaseStatus.SUCCEEDED,
            ExecutionPhaseStatus.FAILED,
        }
    ),
    ExecutionPhaseStatus.SUCCEEDED: frozenset(),
    ExecutionPhaseStatus.FAILED: frozenset(),
    ExecutionPhaseStatus.INTERRUPTED: frozenset(),
}

WORK_ITEM_TRANSITIONS: dict[LedgerWorkItemStatus, frozenset[LedgerWorkItemStatus]] = {
    LedgerWorkItemStatus.PENDING: frozenset(
        {
            LedgerWorkItemStatus.BLOCKED,
            LedgerWorkItemStatus.IN_FLIGHT,
            LedgerWorkItemStatus.CANCELLED,
        }
    ),
    LedgerWorkItemStatus.BLOCKED: frozenset(
        {LedgerWorkItemStatus.PENDING, LedgerWorkItemStatus.CANCELLED}
    ),
    LedgerWorkItemStatus.IN_FLIGHT: frozenset(
        {
            LedgerWorkItemStatus.PENDING,
            LedgerWorkItemStatus.AWAITING_HUMAN,
            LedgerWorkItemStatus.VERIFYING,
            LedgerWorkItemStatus.FAILED,
            LedgerWorkItemStatus.CANCELLED,
        }
    ),
    LedgerWorkItemStatus.AWAITING_HUMAN: frozenset(
        {
            LedgerWorkItemStatus.IN_FLIGHT,
            LedgerWorkItemStatus.FAILED,
            LedgerWorkItemStatus.CANCELLED,
        }
    ),
    LedgerWorkItemStatus.VERIFYING: frozenset(
        {
            LedgerWorkItemStatus.IN_FLIGHT,
            LedgerWorkItemStatus.DONE,
            LedgerWorkItemStatus.FAILED,
        }
    ),
    LedgerWorkItemStatus.DONE: frozenset(),
    LedgerWorkItemStatus.FAILED: frozenset(),
    LedgerWorkItemStatus.CANCELLED: frozenset(),
}

ASSIGNMENT_TRANSITIONS: dict[AssignmentStatus, frozenset[AssignmentStatus]] = {
    AssignmentStatus.OFFERED: frozenset(
        {AssignmentStatus.CLAIMED, AssignmentStatus.EXPIRED, AssignmentStatus.CANCELLED}
    ),
    AssignmentStatus.CLAIMED: frozenset(
        {
            AssignmentStatus.RUNNING,
            AssignmentStatus.RELEASED,
            AssignmentStatus.EXPIRED,
            AssignmentStatus.CANCELLED,
        }
    ),
    AssignmentStatus.RUNNING: frozenset(
        {
            AssignmentStatus.RELEASED,
            AssignmentStatus.COMPLETED,
            AssignmentStatus.FAILED,
            AssignmentStatus.CANCELLED,
        }
    ),
    AssignmentStatus.RELEASED: frozenset(),
    AssignmentStatus.COMPLETED: frozenset(),
    AssignmentStatus.FAILED: frozenset(),
    AssignmentStatus.CANCELLED: frozenset(),
    AssignmentStatus.EXPIRED: frozenset(),
}

VERIFICATION_TRANSITIONS: dict[VerificationStatus, frozenset[VerificationStatus]] = {
    VerificationStatus.PENDING: frozenset(
        {
            VerificationStatus.PASSED,
            VerificationStatus.FAILED,
            VerificationStatus.NEEDS_REVISION,
        }
    ),
    VerificationStatus.PASSED: frozenset(),
    VerificationStatus.FAILED: frozenset(),
    VerificationStatus.NEEDS_REVISION: frozenset(),
}


def can_transition_root_run(current: RootRunStatus, target: RootRunStatus) -> bool:
    _require_exact_enum("current", current, RootRunStatus)
    _require_exact_enum("target", target, RootRunStatus)
    return target in ROOT_RUN_TRANSITIONS[current]


def can_transition_phase(current: ExecutionPhaseStatus, target: ExecutionPhaseStatus) -> bool:
    _require_exact_enum("current", current, ExecutionPhaseStatus)
    _require_exact_enum("target", target, ExecutionPhaseStatus)
    return target in PHASE_TRANSITIONS[current]


def can_transition_work_item(
    current: LedgerWorkItemStatus, target: LedgerWorkItemStatus
) -> bool:
    _require_exact_enum("current", current, LedgerWorkItemStatus)
    _require_exact_enum("target", target, LedgerWorkItemStatus)
    return target in WORK_ITEM_TRANSITIONS[current]


def can_transition_assignment(current: AssignmentStatus, target: AssignmentStatus) -> bool:
    _require_exact_enum("current", current, AssignmentStatus)
    _require_exact_enum("target", target, AssignmentStatus)
    return target in ASSIGNMENT_TRANSITIONS[current]


def can_transition_verification(
    current: VerificationStatus, target: VerificationStatus
) -> bool:
    _require_exact_enum("current", current, VerificationStatus)
    _require_exact_enum("target", target, VerificationStatus)
    return target in VERIFICATION_TRANSITIONS[current]


def runtime_phase_status_value(status: ExecutionPhaseStatus) -> str:
    """Explicit storage-to-runtime projection; VERIFYING is runtime RUNNING."""
    _require_exact_enum("status", status, ExecutionPhaseStatus)
    if status is ExecutionPhaseStatus.VERIFYING:
        return ExecutionPhaseStatus.RUNNING.value
    return cast(str, status.value)
