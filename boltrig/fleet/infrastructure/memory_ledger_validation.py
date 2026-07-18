"""Fail-closed hierarchy and lifecycle checks for the memory ledger adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast

from boltrig.fleet.infrastructure.memory_ledger_state import (
    MemoryLedgerState,
    aggregate_key,
    get_version,
    record_id,
    record_kind,
    root_for,
    scope_key,
    workspace_key,
)
from boltrig.fleet.infrastructure.memory_ledger_transitions import validate_transition
from boltrig.fleet.ports.execution_ledger import AtomicLedgerWrite
from boltrig.models import (
    AssignmentStatus,
    EngineOwner,
    ExecutionAssignment,
    ExecutionEventKind,
    ExecutionPhase,
    ExecutionPhaseStatus,
    ExecutionResult,
    ExecutionRootRun,
    ExecutionVerification,
    ExecutionWorkItem,
    LedgerCommandKind,
    LedgerMutationStatus,
    LedgerWorkItemStatus,
    ResultStatus,
    RootRunStatus,
    RuntimeIdentityStatus,
)


@dataclass(frozen=True)
class ValidationDecision:
    status: LedgerMutationStatus | None
    previous_version: int


def validate_write(
    state: MemoryLedgerState, write: AtomicLedgerWrite, *, now: datetime
) -> ValidationDecision:
    command = write.command
    kind = record_kind(write.record)
    item_id = record_id(write.record)
    previous = get_version(state, kind, command.scope, item_id)
    if command.aggregate_kind is not kind or command.aggregate_id != item_id:
        return ValidationDecision(LedgerMutationStatus.REJECTED, previous)
    if not _command_accepts_record(write):
        return ValidationDecision(LedgerMutationStatus.REJECTED, previous)
    if not _event_matches_write(write, now=now):
        return ValidationDecision(LedgerMutationStatus.REJECTED, previous)
    if command.expected_version != previous:
        return ValidationDecision(LedgerMutationStatus.CONFLICT, previous)
    if _is_create(command.kind):
        if previous != 0:
            return ValidationDecision(LedgerMutationStatus.CONFLICT, previous)
        return ValidationDecision(_validate_create(state, write, now=now), previous)
    if previous == 0:
        return ValidationDecision(LedgerMutationStatus.NOT_FOUND, previous)
    return ValidationDecision(validate_transition(state, write, now=now), previous)


def _command_accepts_record(write: AtomicLedgerWrite) -> bool:
    kind = write.command.kind
    record = write.record
    expected: dict[LedgerCommandKind, tuple[type[object], ...]] = {
        LedgerCommandKind.CREATE_ROOT: (ExecutionRootRun,),
        LedgerCommandKind.CREATE_PHASE: (ExecutionPhase,),
        LedgerCommandKind.ENQUEUE_WORK: (ExecutionWorkItem,),
        LedgerCommandKind.ASSIGN_WORK: (ExecutionAssignment,),
        LedgerCommandKind.REPLACE_ASSIGNMENT: (ExecutionAssignment,),
        LedgerCommandKind.RECORD_RESULT: (ExecutionResult,),
        LedgerCommandKind.RECORD_VERIFICATION: (ExecutionVerification,),
        LedgerCommandKind.TRANSITION_STATUS: (
            ExecutionRootRun,
            ExecutionPhase,
            ExecutionWorkItem,
            ExecutionAssignment,
            ExecutionVerification,
        ),
        LedgerCommandKind.CANCEL: (
            ExecutionRootRun,
            ExecutionPhase,
            ExecutionWorkItem,
            ExecutionAssignment,
        ),
    }
    if type(record) not in expected[kind]:
        return False
    if type(record) is ExecutionAssignment:
        replacement = record.replaces_assignment_id is not None
        if kind is LedgerCommandKind.ASSIGN_WORK and replacement:
            return False
        if kind is LedgerCommandKind.REPLACE_ASSIGNMENT and not replacement:
            return False
    return True


def _event_matches_write(write: AtomicLedgerWrite, *, now: datetime) -> bool:
    command = write.command
    event = write.event
    if (
        event.aggregate_kind is not command.aggregate_kind
        or event.aggregate_id != command.aggregate_id
        or event.causation_command_id != command.id
        or event.source_owner is not EngineOwner.BOLTRIG
        or command.issued_at > now
        or event.occurred_at < command.issued_at
        or event.occurred_at > now
    ):
        return False
    expected: dict[LedgerCommandKind, frozenset[ExecutionEventKind]] = {
        LedgerCommandKind.CREATE_ROOT: frozenset({ExecutionEventKind.CREATED}),
        LedgerCommandKind.CREATE_PHASE: frozenset({ExecutionEventKind.CREATED}),
        LedgerCommandKind.ENQUEUE_WORK: frozenset({ExecutionEventKind.CREATED}),
        LedgerCommandKind.ASSIGN_WORK: frozenset({ExecutionEventKind.CREATED}),
        LedgerCommandKind.REPLACE_ASSIGNMENT: frozenset({ExecutionEventKind.CREATED}),
        LedgerCommandKind.RECORD_RESULT: frozenset({ExecutionEventKind.RESULT_RECORDED}),
        LedgerCommandKind.RECORD_VERIFICATION: frozenset(
            {ExecutionEventKind.VERIFICATION_RECORDED}
        ),
        LedgerCommandKind.TRANSITION_STATUS: frozenset(
            {ExecutionEventKind.STATUS_CHANGED, ExecutionEventKind.INTERRUPTED}
        ),
        LedgerCommandKind.CANCEL: frozenset(
            {ExecutionEventKind.STATUS_CHANGED, ExecutionEventKind.INTERRUPTED}
        ),
    }
    return event.kind in expected[command.kind] and all(
        intent.available_at >= event.occurred_at
        and intent.delivery_key != event.ingestion_idempotency_key
        for intent in write.outbox
    )


def _is_create(kind: LedgerCommandKind) -> bool:
    return kind not in {LedgerCommandKind.TRANSITION_STATUS, LedgerCommandKind.CANCEL}


def _validate_create(
    state: MemoryLedgerState, write: AtomicLedgerWrite, *, now: datetime
) -> LedgerMutationStatus | None:
    record = write.record
    if type(record) is ExecutionRootRun:
        return (
            None
            if record.status is RootRunStatus.PENDING and record.version == 1
            else LedgerMutationStatus.REJECTED
        )
    root = root_for(state, record.scope)
    if root is None:
        return LedgerMutationStatus.NOT_FOUND
    if root.status not in {RootRunStatus.PENDING, RootRunStatus.RUNNING}:
        return LedgerMutationStatus.REJECTED
    if type(record) is ExecutionPhase:
        return _validate_new_phase(state, record, root)
    if type(record) is ExecutionWorkItem:
        return _validate_new_work(state, record)
    if type(record) is ExecutionAssignment:
        return _validate_new_assignment(state, record, root, now=now)
    if type(record) is ExecutionResult:
        return _validate_new_result(state, record)
    return _validate_new_verification(state, cast(ExecutionVerification, record))


def _validate_new_phase(
    state: MemoryLedgerState, phase: ExecutionPhase, root: ExecutionRootRun
) -> LedgerMutationStatus | None:
    if phase.version != 1 or phase.status is not ExecutionPhaseStatus.PENDING:
        return LedgerMutationStatus.REJECTED
    if phase.policy_generation != root.policy_generation:
        return LedgerMutationStatus.REJECTED
    key = scope_key(phase.scope)
    siblings = tuple(value for (scope, _), value in state.phases.items() if scope == key)
    if any(item.ordinal == phase.ordinal for item in siblings):
        return LedgerMutationStatus.CONFLICT
    dependencies = tuple(state.phases.get((key, item)) for item in phase.dependencies)
    if any(item is None for item in dependencies):
        return LedgerMutationStatus.NOT_FOUND
    if any(item is not None and item.ordinal >= phase.ordinal for item in dependencies):
        return LedgerMutationStatus.REJECTED
    return None


def _validate_new_work(
    state: MemoryLedgerState, work: ExecutionWorkItem
) -> LedgerMutationStatus | None:
    if work.version != 1 or work.status is not LedgerWorkItemStatus.PENDING:
        return LedgerMutationStatus.REJECTED
    phase = state.phases.get(aggregate_key(work.scope, work.phase_id))
    if phase is None:
        return LedgerMutationStatus.NOT_FOUND
    key = scope_key(work.scope)
    siblings = tuple(
        value
        for (scope, _), value in state.work_items.items()
        if scope == key and value.phase_id == work.phase_id
    )
    if any(item.ordinal == work.ordinal for item in siblings):
        return LedgerMutationStatus.CONFLICT
    dependencies = tuple(state.work_items.get((key, item)) for item in work.dependencies)
    if any(item is None for item in dependencies):
        return LedgerMutationStatus.NOT_FOUND
    if any(item is not None and item.phase_id != work.phase_id for item in dependencies):
        return LedgerMutationStatus.REJECTED
    if work.parent_id is not None:
        parent = state.work_items.get((key, work.parent_id))
        if parent is None:
            return LedgerMutationStatus.NOT_FOUND
        if parent.phase_id != work.phase_id:
            return LedgerMutationStatus.REJECTED
    return None


def _validate_new_assignment(
    state: MemoryLedgerState,
    assignment: ExecutionAssignment,
    root: ExecutionRootRun,
    *,
    now: datetime,
) -> LedgerMutationStatus | None:
    del now
    if assignment.version != 1 or assignment.status is not AssignmentStatus.OFFERED:
        return LedgerMutationStatus.REJECTED
    if root.status is not RootRunStatus.RUNNING:
        return LedgerMutationStatus.REJECTED
    phase = state.phases.get(aggregate_key(assignment.scope, assignment.phase_id))
    work = state.work_items.get(aggregate_key(assignment.scope, assignment.work_item_id))
    identity = state.identities.get(
        (workspace_key(assignment.scope.workspace), assignment.runtime_identity_id)
    )
    if phase is None or work is None or identity is None:
        return LedgerMutationStatus.NOT_FOUND
    if work.phase_id != phase.id or phase.status not in {
        ExecutionPhaseStatus.STARTING,
        ExecutionPhaseStatus.RUNNING,
    }:
        return LedgerMutationStatus.REJECTED
    if assignment.authority.policy_generation != phase.policy_generation:
        return LedgerMutationStatus.REJECTED
    if identity.status is not RuntimeIdentityStatus.ACTIVE:
        return LedgerMutationStatus.REJECTED
    if identity.workspace != assignment.scope.workspace:
        return LedgerMutationStatus.REJECTED
    if work.status not in {LedgerWorkItemStatus.PENDING, LedgerWorkItemStatus.IN_FLIGHT}:
        return LedgerMutationStatus.REJECTED
    if not _dependencies_done(state, work):
        return LedgerMutationStatus.REJECTED
    return _validate_attempt(state, assignment, phase)


def _validate_attempt(
    state: MemoryLedgerState, assignment: ExecutionAssignment, phase: ExecutionPhase
) -> LedgerMutationStatus | None:
    key = scope_key(assignment.scope)
    siblings = tuple(
        item
        for (scope, _), item in state.assignments.items()
        if scope == key and item.work_item_id == assignment.work_item_id
    )
    live = {AssignmentStatus.OFFERED, AssignmentStatus.CLAIMED, AssignmentStatus.RUNNING}
    if any(item.status in live for item in siblings):
        return LedgerMutationStatus.CONFLICT
    replaced = assignment.replaces_assignment_id
    if replaced is None:
        return None if assignment.attempt == 1 and not siblings else LedgerMutationStatus.REJECTED
    previous = state.assignments.get((key, replaced))
    if previous is None:
        return LedgerMutationStatus.NOT_FOUND
    if previous.work_item_id != assignment.work_item_id or previous.phase_id != assignment.phase_id:
        return LedgerMutationStatus.REJECTED
    if previous.status in live or assignment.attempt != previous.attempt + 1:
        return LedgerMutationStatus.REJECTED
    if any(item.replaces_assignment_id == previous.id for item in siblings):
        return LedgerMutationStatus.CONFLICT
    if previous.attempt != max(item.attempt for item in siblings):
        return LedgerMutationStatus.REJECTED
    if assignment.attempt > phase.retry.max_attempts:
        return LedgerMutationStatus.REJECTED
    return None


def _validate_new_result(
    state: MemoryLedgerState, result: ExecutionResult
) -> LedgerMutationStatus | None:
    assignment = state.assignments.get(aggregate_key(result.scope, result.assignment_id))
    if assignment is None:
        return LedgerMutationStatus.NOT_FOUND
    if (assignment.phase_id, assignment.work_item_id) != (result.phase_id, result.work_item_id):
        return LedgerMutationStatus.REJECTED
    if any(
        item.scope == result.scope and item.assignment_id == result.assignment_id
        for item in state.results.values()
    ):
        return LedgerMutationStatus.CONFLICT
    compatible = {
        ResultStatus.SUCCEEDED: {AssignmentStatus.RUNNING, AssignmentStatus.COMPLETED},
        ResultStatus.FAILED: {AssignmentStatus.RUNNING, AssignmentStatus.FAILED},
        ResultStatus.INTERRUPTED: {
            AssignmentStatus.RUNNING,
            AssignmentStatus.CANCELLED,
            AssignmentStatus.RELEASED,
        },
    }
    return None if assignment.status in compatible[result.status] else LedgerMutationStatus.REJECTED


def _validate_new_verification(
    state: MemoryLedgerState, verification: ExecutionVerification
) -> LedgerMutationStatus | None:
    result = state.results.get(aggregate_key(verification.scope, verification.result_id))
    if result is None:
        return LedgerMutationStatus.NOT_FOUND
    if (result.phase_id, result.work_item_id) != (
        verification.phase_id,
        verification.work_item_id,
    ):
        return LedgerMutationStatus.REJECTED
    if any(
        item.scope == verification.scope and item.result_id == verification.result_id
        for item in state.verifications.values()
    ):
        return LedgerMutationStatus.CONFLICT
    return None


def _dependencies_done(state: MemoryLedgerState, work: ExecutionWorkItem) -> bool:
    key = scope_key(work.scope)
    return all(
        (dependency := state.work_items.get((key, item))) is not None
        and dependency.phase_id == work.phase_id
        and dependency.status is LedgerWorkItemStatus.DONE
        for item in work.dependencies
    )


__all__ = ["ValidationDecision", "validate_write"]
