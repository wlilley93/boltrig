"""Runtime identity and Codex binding ownership for the memory ledger."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from boltrig.fleet.infrastructure.memory_ledger_capacity import binding_fits, identity_fits
from boltrig.fleet.infrastructure.memory_ledger_state import (
    MemoryLedgerLimits,
    MemoryLedgerState,
    aggregate_key,
    root_for,
    scope_key,
    workspace_key,
)
from boltrig.fleet.ports.execution_ledger import (
    AppendStatus,
    BindingWriteOutcome,
    CodexBinding,
    RuntimeIdentityWriteOutcome,
)
from boltrig.models import (
    AssignmentStatus,
    CodexBindingKind,
    CodexItemBinding,
    CodexThreadBinding,
    CodexTurnBinding,
    ExecutionPhaseStatus,
    RootRunStatus,
    RuntimeIdentity,
    RuntimeIdentityStatus,
)

_BINDABLE_ASSIGNMENTS = frozenset({AssignmentStatus.CLAIMED, AssignmentStatus.RUNNING})
_BINDABLE_PHASES = frozenset(
    {
        ExecutionPhaseStatus.STARTING,
        ExecutionPhaseStatus.RUNNING,
        ExecutionPhaseStatus.AWAITING_APPROVAL,
        ExecutionPhaseStatus.VERIFYING,
    }
)


def write_runtime_identity_locked(
    state: MemoryLedgerState,
    limits: MemoryLedgerLimits,
    identity: RuntimeIdentity,
    *,
    expected_generation: int,
    now: datetime,
) -> RuntimeIdentityWriteOutcome:
    key = (workspace_key(identity.workspace), identity.id)
    current = state.identities.get(key)
    if current == identity:
        expected_replay = 0 if identity.generation == 1 else identity.generation - 1
        status = (
            AppendStatus.REPLAYED
            if expected_generation == expected_replay
            else AppendStatus.CONFLICT
        )
        return RuntimeIdentityWriteOutcome(status, current)
    if identity.created_at > now or (
        identity.revoked_at is not None and identity.revoked_at > now
    ):
        return RuntimeIdentityWriteOutcome(AppendStatus.REJECTED, current)
    if current is None:
        if not identity_fits(state, limits):
            return RuntimeIdentityWriteOutcome(AppendStatus.REJECTED, None)
        if not _valid_new_identity(identity, expected_generation):
            return RuntimeIdentityWriteOutcome(AppendStatus.REJECTED, None)
    elif not _valid_identity_revision(current, identity, expected_generation):
        status = (
            AppendStatus.CONFLICT
            if current.generation != expected_generation
            else AppendStatus.REJECTED
        )
        return RuntimeIdentityWriteOutcome(status, current)
    state.identities[key] = identity
    return RuntimeIdentityWriteOutcome(AppendStatus.INSERTED, identity)


def append_binding_locked(
    state: MemoryLedgerState,
    limits: MemoryLedgerLimits,
    binding: CodexBinding,
    *,
    now: datetime,
) -> BindingWriteOutcome:
    current = _binding_current(state, binding)
    if current == binding:
        return BindingWriteOutcome(AppendStatus.REPLAYED, current)
    if current is not None:
        return BindingWriteOutcome(AppendStatus.CONFLICT, current)
    status = _validate_binding(state, binding, now=now)
    if status is not AppendStatus.INSERTED or not binding_fits(state, limits):
        rejected = status if status is not AppendStatus.INSERTED else AppendStatus.REJECTED
        return BindingWriteOutcome(rejected, None)
    _put_binding(state, binding)
    return BindingWriteOutcome(AppendStatus.INSERTED, binding)


def _binding_current(
    state: MemoryLedgerState, binding: CodexBinding
) -> CodexBinding | None:
    key = scope_key(binding.scope)
    if type(binding) is CodexThreadBinding:
        return state.threads.get((key, binding.thread_id))
    if type(binding) is CodexTurnBinding:
        return state.turns.get((key, binding.thread.thread_id, binding.turn_id))
    item = cast(CodexItemBinding, binding)
    return state.items.get(
        (key, item.turn.thread.thread_id, item.turn.turn_id, item.item_id)
    )


def _validate_binding(
    state: MemoryLedgerState, binding: CodexBinding, *, now: datetime
) -> AppendStatus:
    assignment = state.assignments.get(
        aggregate_key(binding.scope, _binding_assignment_id(binding))
    )
    phase = state.phases.get(aggregate_key(binding.scope, _binding_phase_id(binding)))
    identity_id = _binding_identity_id(binding)
    identity = state.identities.get((workspace_key(binding.scope.workspace), identity_id))
    root = root_for(state, binding.scope)
    if assignment is None or phase is None or identity is None or root is None:
        return AppendStatus.NOT_FOUND
    if (
        root.status is not RootRunStatus.RUNNING
        or phase.status not in _BINDABLE_PHASES
        or assignment.status not in _BINDABLE_ASSIGNMENTS
        or identity.status is not RuntimeIdentityStatus.ACTIVE
    ):
        return AppendStatus.REJECTED
    if (assignment.phase_id, assignment.runtime_identity_id) != (phase.id, identity_id):
        return AppendStatus.REJECTED
    if binding.bound_at > now or binding.bound_at < max(
        assignment.created_at, phase.created_at, identity.created_at
    ):
        return AppendStatus.REJECTED
    if type(binding) is CodexThreadBinding:
        return _validate_thread_parent(state, binding)
    thread = (
        binding.thread
        if type(binding) is CodexTurnBinding
        else cast(CodexItemBinding, binding).turn.thread
    )
    stored_thread = state.threads.get((scope_key(binding.scope), thread.thread_id))
    if stored_thread != thread or binding.bound_at < thread.bound_at:
        return AppendStatus.NOT_FOUND
    if type(binding) is CodexTurnBinding:
        return _validate_turn_parent(state, binding)
    item = cast(CodexItemBinding, binding)
    stored_turn = state.turns.get(
        (scope_key(binding.scope), item.turn.thread.thread_id, item.turn.turn_id)
    )
    if stored_turn != item.turn or binding.bound_at < item.turn.bound_at:
        return AppendStatus.NOT_FOUND
    return _validate_item_parent(state, item)


def _validate_thread_parent(
    state: MemoryLedgerState, binding: CodexThreadBinding
) -> AppendStatus:
    key = scope_key(binding.scope)
    if binding.kind is CodexBindingKind.PHASE:
        duplicate = any(
            item.scope == binding.scope
            and item.assignment_id == binding.assignment_id
            and item.kind is CodexBindingKind.PHASE
            for item in state.threads.values()
        )
        return AppendStatus.CONFLICT if duplicate else AppendStatus.INSERTED
    parent = state.threads.get((key, binding.native_parent_thread_id or ""))
    if parent is None:
        return AppendStatus.NOT_FOUND
    if (
        parent.kind is not CodexBindingKind.PHASE
        or (parent.phase_id, parent.assignment_id, parent.runtime_identity_id)
        != (binding.phase_id, binding.assignment_id, binding.runtime_identity_id)
        or binding.bound_at < parent.bound_at
    ):
        return AppendStatus.REJECTED
    return AppendStatus.INSERTED


def _validate_turn_parent(
    state: MemoryLedgerState, binding: CodexTurnBinding
) -> AppendStatus:
    if binding.native_parent_turn_id is None:
        return AppendStatus.INSERTED
    parent = state.turns.get(
        (
            scope_key(binding.scope),
            binding.thread.thread_id,
            binding.native_parent_turn_id,
        )
    )
    if parent is None:
        return AppendStatus.NOT_FOUND
    if parent.kind is not CodexBindingKind.PHASE or binding.bound_at < parent.bound_at:
        return AppendStatus.REJECTED
    return AppendStatus.INSERTED


def _validate_item_parent(
    state: MemoryLedgerState, binding: CodexItemBinding
) -> AppendStatus:
    if binding.native_parent_item_id is None:
        return AppendStatus.INSERTED
    parent = state.items.get(
        (
            scope_key(binding.scope),
            binding.turn.thread.thread_id,
            binding.turn.turn_id,
            binding.native_parent_item_id,
        )
    )
    if parent is None:
        return AppendStatus.NOT_FOUND
    if parent.kind is not CodexBindingKind.PHASE or binding.bound_at < parent.bound_at:
        return AppendStatus.REJECTED
    return AppendStatus.INSERTED


def _put_binding(state: MemoryLedgerState, binding: CodexBinding) -> None:
    key = scope_key(binding.scope)
    if type(binding) is CodexThreadBinding:
        state.threads[(key, binding.thread_id)] = binding
    elif type(binding) is CodexTurnBinding:
        state.turns[(key, binding.thread.thread_id, binding.turn_id)] = binding
    else:
        item = cast(CodexItemBinding, binding)
        state.items[
            (key, item.turn.thread.thread_id, item.turn.turn_id, item.item_id)
        ] = item


def _valid_new_identity(identity: RuntimeIdentity, expected: int) -> bool:
    return (
        expected == 0
        and identity.generation == 1
        and identity.status is RuntimeIdentityStatus.ACTIVE
    )


def _valid_identity_revision(
    current: RuntimeIdentity, target: RuntimeIdentity, expected: int
) -> bool:
    return bool(
        current.generation == expected
        and target.generation == current.generation + 1
        and current.status is RuntimeIdentityStatus.ACTIVE
        and target.status is RuntimeIdentityStatus.REVOKED
        and current.id == target.id
        and current.principal == target.principal
        and current.workspace == target.workspace
        and current.created_at == target.created_at
    )


def _binding_assignment_id(binding: CodexBinding) -> str:
    if type(binding) is CodexThreadBinding:
        return binding.assignment_id
    if type(binding) is CodexTurnBinding:
        return binding.thread.assignment_id
    return cast(CodexItemBinding, binding).turn.thread.assignment_id


def _binding_identity_id(binding: CodexBinding) -> str:
    return (
        binding.runtime_identity_id
        if type(binding) is CodexThreadBinding
        else _binding_thread(binding).runtime_identity_id
    )


def _binding_phase_id(binding: CodexBinding) -> str:
    if type(binding) is CodexThreadBinding:
        return binding.phase_id
    return _binding_thread(binding).phase_id


def _binding_thread(binding: CodexBinding) -> CodexThreadBinding:
    if type(binding) is CodexTurnBinding:
        return binding.thread
    return cast(CodexItemBinding, binding).turn.thread


__all__ = ["append_binding_locked", "write_runtime_identity_locked"]
