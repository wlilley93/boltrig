"""Lifecycle validation for canonical in-memory ledger revisions."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from boltrig.fleet.infrastructure.memory_ledger_state import (
    MemoryLedgerState,
    aggregate_key,
    get_record,
    record_id,
    record_kind,
    root_for,
    scope_key,
)
from boltrig.fleet.ports.execution_ledger import AtomicLedgerWrite
from boltrig.models import (
    AssignmentStatus,
    ExecutionAssignment,
    ExecutionPhase,
    ExecutionPhaseStatus,
    ExecutionRootRun,
    ExecutionVerification,
    ExecutionWorkItem,
    LedgerCommandKind,
    LedgerMutationStatus,
    LedgerWorkItemStatus,
    ResultStatus,
    RootRunStatus,
    VerificationStatus,
    can_transition_assignment,
    can_transition_phase,
    can_transition_root_run,
    can_transition_verification,
    can_transition_work_item,
)

_LIVE_ASSIGNMENTS = frozenset(
    {AssignmentStatus.OFFERED, AssignmentStatus.CLAIMED, AssignmentStatus.RUNNING}
)
_TERMINAL_ASSIGNMENTS = frozenset(set(AssignmentStatus) - set(_LIVE_ASSIGNMENTS))
_TERMINAL_WORK = frozenset(
    {LedgerWorkItemStatus.DONE, LedgerWorkItemStatus.FAILED, LedgerWorkItemStatus.CANCELLED}
)
_TERMINAL_PHASES = frozenset(
    {
        ExecutionPhaseStatus.SUCCEEDED,
        ExecutionPhaseStatus.FAILED,
        ExecutionPhaseStatus.INTERRUPTED,
    }
)


def validate_transition(
    state: MemoryLedgerState, write: AtomicLedgerWrite, *, now: datetime
) -> LedgerMutationStatus | None:
    record = write.record
    current = get_record(state, record_kind(record), record.scope, record_id(record))
    if current is None or type(current) is not type(record):
        return LedgerMutationStatus.NOT_FOUND
    if not _transition_shape(current, record) or not _transition_is_legal(current, record):
        return LedgerMutationStatus.REJECTED
    cancellation = _is_cancel_target(record)
    if cancellation != (write.command.kind is LedgerCommandKind.CANCEL):
        return LedgerMutationStatus.REJECTED
    if type(record) is ExecutionRootRun:
        return _validate_root_terminal(state, record)
    root = root_for(state, record.scope)
    if root is None or not _root_allows_transition(root, record):
        return LedgerMutationStatus.REJECTED
    return _validate_transition_context(state, current, record, now=now)


def _transition_shape(current: object, target: object) -> bool:
    if type(current) is ExecutionRootRun and type(target) is ExecutionRootRun:
        return replace(
            current,
            status=target.status,
            cancellation=target.cancellation,
            final_synthesis_digest=target.final_synthesis_digest,
            version=current.version + 1,
        ) == target
    if type(current) is ExecutionPhase and type(target) is ExecutionPhase:
        return replace(
            current,
            status=target.status,
            terminal_outcome=target.terminal_outcome,
            version=current.version + 1,
        ) == target
    if type(current) is ExecutionWorkItem and type(target) is ExecutionWorkItem:
        return replace(current, status=target.status, version=current.version + 1) == target
    if type(current) is ExecutionAssignment and type(target) is ExecutionAssignment:
        return replace(
            current, status=target.status, lease=target.lease, version=current.version + 1
        ) == target
    if type(current) is ExecutionVerification and type(target) is ExecutionVerification:
        return replace(
            current,
            status=target.status,
            checks=target.checks,
            verified_by=target.verified_by,
        ) == target
    return False


def _transition_is_legal(current: object, target: object) -> bool:
    if type(current) is ExecutionRootRun and type(target) is ExecutionRootRun:
        return can_transition_root_run(current.status, target.status)
    if type(current) is ExecutionPhase and type(target) is ExecutionPhase:
        return can_transition_phase(current.status, target.status)
    if type(current) is ExecutionWorkItem and type(target) is ExecutionWorkItem:
        return can_transition_work_item(current.status, target.status)
    if type(current) is ExecutionAssignment and type(target) is ExecutionAssignment:
        return can_transition_assignment(current.status, target.status)
    if type(current) is ExecutionVerification and type(target) is ExecutionVerification:
        return can_transition_verification(current.status, target.status)
    return False


def _is_cancel_target(record: object) -> bool:
    if type(record) is ExecutionRootRun:
        return record.status in {RootRunStatus.CANCELLING, RootRunStatus.CANCELLED}
    if type(record) is ExecutionPhase:
        return record.status in {
            ExecutionPhaseStatus.INTERRUPTING,
            ExecutionPhaseStatus.INTERRUPTED,
        }
    if type(record) is ExecutionWorkItem:
        return record.status is LedgerWorkItemStatus.CANCELLED
    if type(record) is ExecutionAssignment:
        return record.status is AssignmentStatus.CANCELLED
    return False


def _validate_root_terminal(
    state: MemoryLedgerState, target: ExecutionRootRun
) -> LedgerMutationStatus | None:
    key = scope_key(target.scope)
    phases = tuple(value for (scope, _), value in state.phases.items() if scope == key)
    if target.status is RootRunStatus.SUCCEEDED:
        if not phases or any(item.status is not ExecutionPhaseStatus.SUCCEEDED for item in phases):
            return LedgerMutationStatus.REJECTED
    if target.status in {RootRunStatus.CANCELLED, RootRunStatus.FAILED}:
        if any(item.status not in _TERMINAL_PHASES for item in phases):
            return LedgerMutationStatus.REJECTED
        if any(
            item.scope == target.scope and item.status not in _TERMINAL_WORK
            for item in state.work_items.values()
        ):
            return LedgerMutationStatus.REJECTED
        if any(
            item.scope == target.scope and item.status not in _TERMINAL_ASSIGNMENTS
            for item in state.assignments.values()
        ):
            return LedgerMutationStatus.REJECTED
    return None


def _root_allows_transition(root: ExecutionRootRun, record: object) -> bool:
    if root.status is RootRunStatus.RUNNING:
        return True
    if root.status is not RootRunStatus.CANCELLING:
        return False
    if type(record) is ExecutionPhase:
        return record.status in {
            ExecutionPhaseStatus.INTERRUPTING,
            ExecutionPhaseStatus.INTERRUPTED,
            ExecutionPhaseStatus.FAILED,
        }
    if type(record) is ExecutionWorkItem:
        return record.status in {LedgerWorkItemStatus.CANCELLED, LedgerWorkItemStatus.FAILED}
    if type(record) is ExecutionAssignment:
        return record.status in {
            AssignmentStatus.CANCELLED,
            AssignmentStatus.FAILED,
            AssignmentStatus.RELEASED,
        }
    return False


def _validate_transition_context(
    state: MemoryLedgerState, current: object, target: object, *, now: datetime
) -> LedgerMutationStatus | None:
    if type(target) is ExecutionPhase:
        return _validate_phase_transition(state, target)
    if type(target) is ExecutionWorkItem:
        return _validate_work_transition(state, target)
    if type(current) is ExecutionAssignment and type(target) is ExecutionAssignment:
        return _validate_assignment_transition(current, target, now=now)
    return None


def _validate_phase_transition(
    state: MemoryLedgerState, target: ExecutionPhase
) -> LedgerMutationStatus | None:
    if target.status is ExecutionPhaseStatus.STARTING:
        key = scope_key(target.scope)
        dependencies = tuple(state.phases.get((key, item)) for item in target.dependencies)
        if any(
            item is None or item.status is not ExecutionPhaseStatus.SUCCEEDED
            for item in dependencies
        ):
            return LedgerMutationStatus.REJECTED
    works = tuple(
        item
        for item in state.work_items.values()
        if item.scope == target.scope and item.phase_id == target.id
    )
    assignments = tuple(
        item
        for item in state.assignments.values()
        if item.scope == target.scope and item.phase_id == target.id
    )
    if target.status is ExecutionPhaseStatus.SUCCEEDED and any(
        item.status is not LedgerWorkItemStatus.DONE for item in works
    ):
        return LedgerMutationStatus.REJECTED
    if target.status in {ExecutionPhaseStatus.INTERRUPTED, ExecutionPhaseStatus.FAILED}:
        if any(item.status not in _TERMINAL_WORK for item in works):
            return LedgerMutationStatus.REJECTED
        if any(item.status not in _TERMINAL_ASSIGNMENTS for item in assignments):
            return LedgerMutationStatus.REJECTED
    return None


def _validate_work_transition(
    state: MemoryLedgerState, target: ExecutionWorkItem
) -> LedgerMutationStatus | None:
    if target.status is LedgerWorkItemStatus.IN_FLIGHT:
        phase = state.phases.get(aggregate_key(target.scope, target.phase_id))
        if (
            phase is None
            or phase.status is not ExecutionPhaseStatus.RUNNING
            or not _dependencies_done(state, target)
        ):
            return LedgerMutationStatus.REJECTED
    assignments = tuple(
        item
        for item in state.assignments.values()
        if item.scope == target.scope and item.work_item_id == target.id
    )
    if target.status in _TERMINAL_WORK and any(
        item.status in _LIVE_ASSIGNMENTS for item in assignments
    ):
        return LedgerMutationStatus.REJECTED
    if target.status is LedgerWorkItemStatus.DONE and not _work_has_verified_result(
        state, target, assignments
    ):
        return LedgerMutationStatus.REJECTED
    return None


def _work_has_verified_result(
    state: MemoryLedgerState,
    work: ExecutionWorkItem,
    assignments: tuple[ExecutionAssignment, ...],
) -> bool:
    completed = {item.id for item in assignments if item.status is AssignmentStatus.COMPLETED}
    results = tuple(
        item
        for item in state.results.values()
        if item.scope == work.scope
        and item.work_item_id == work.id
        and item.assignment_id in completed
        and item.status is ResultStatus.SUCCEEDED
    )
    if not results:
        return False
    if not work.requires_verification:
        return True
    result_ids = {item.id for item in results}
    return any(
        item.scope == work.scope
        and item.work_item_id == work.id
        and item.result_id in result_ids
        and item.status is VerificationStatus.PASSED
        for item in state.verifications.values()
    )


def _validate_assignment_transition(
    current: ExecutionAssignment, target: ExecutionAssignment, *, now: datetime
) -> LedgerMutationStatus | None:
    if target.status in {AssignmentStatus.CLAIMED, AssignmentStatus.RUNNING}:
        if target.lease is None or target.lease.expires_at <= now:
            return LedgerMutationStatus.REJECTED
    if current.lease is not None and target.lease != current.lease:
        return LedgerMutationStatus.REJECTED
    if current.status is AssignmentStatus.OFFERED and target.status is AssignmentStatus.CLAIMED:
        return None if target.lease is not None else LedgerMutationStatus.REJECTED
    if current.status is AssignmentStatus.CLAIMED and target.status is AssignmentStatus.RUNNING:
        return None if target.lease == current.lease else LedgerMutationStatus.REJECTED
    return None


def _dependencies_done(state: MemoryLedgerState, work: ExecutionWorkItem) -> bool:
    key = scope_key(work.scope)
    return all(
        (dependency := state.work_items.get((key, item))) is not None
        and dependency.phase_id == work.phase_id
        and dependency.status is LedgerWorkItemStatus.DONE
        for item in work.dependencies
    )


__all__ = ["validate_transition"]
