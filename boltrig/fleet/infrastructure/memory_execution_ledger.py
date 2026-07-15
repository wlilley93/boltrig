"""Atomic, tenant-scoped in-memory adapter for the canonical execution ledger."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import cast

from boltrig.fleet.infrastructure.memory_ledger_capacity import ledger_write_fits
from boltrig.fleet.infrastructure.memory_ledger_events import (
    append_event_locked,
    event_preflight,
    materialize_event,
    record_event,
)
from boltrig.fleet.infrastructure.memory_ledger_runtime import (
    append_binding_locked,
    write_runtime_identity_locked,
)
from boltrig.fleet.infrastructure.memory_ledger_state import (
    MemoryLedgerLimits,
    MemoryLedgerState,
    StoredCommand,
    aggregate_key,
    put_record,
    scope_key,
    workspace_key,
)
from boltrig.fleet.infrastructure.memory_ledger_validation import validate_write
from boltrig.fleet.ports.execution_ledger import (
    MAX_LEDGER_PAGE_SIZE,
    AtomicEventAppend,
    AtomicLedgerWrite,
    BindingWriteOutcome,
    CodexBinding,
    EventAppendOutcome,
    RuntimeIdentityWriteOutcome,
)
from boltrig.models import (
    CodexItemBinding,
    CodexThreadBinding,
    CodexTurnBinding,
    ExecutionAssignment,
    ExecutionOutboxRecord,
    ExecutionPhase,
    ExecutionResult,
    ExecutionRootRun,
    ExecutionScopeRef,
    ExecutionVerification,
    ExecutionWorkItem,
    LedgerMutationOutcome,
    LedgerMutationStatus,
    RecordedExecutionEvent,
    RuntimeIdentity,
    WorkspaceScopeRef,
    classify_command_replay,
)
from boltrig.models.base import utcnow
from boltrig.models.execution_commands import CommandReplayDecision
from boltrig.models.execution_scope import MAX_SIGNED_BIGINT


class MemoryExecutionLedger:
    """Serializable non-evicting fake that fails closed at configured limits."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = utcnow,
        limits: MemoryLedgerLimits | None = None,
    ) -> None:
        self._state = MemoryLedgerState()
        self._clock = clock
        self._limits = limits or MemoryLedgerLimits()
        self._lock = asyncio.Lock()

    async def commit(self, write: AtomicLedgerWrite) -> LedgerMutationOutcome:
        if type(write) is not AtomicLedgerWrite:
            raise TypeError("write must be an exact AtomicLedgerWrite")
        async with self._lock:
            replay = self._replay_outcome(write)
            if replay is not None:
                return replay
            now = _aware("ledger clock", self._clock())
            decision = validate_write(self._state, write, now=now)
            append = AtomicEventAppend(write.event, write.outbox)
            status = decision.status or event_preflight(self._state, append)
            if status is None and not ledger_write_fits(self._state, self._limits, write):
                status = LedgerMutationStatus.REJECTED
            if status is not None:
                return self._store_terminal_command(write, status, decision.previous_version)
            recorded, outbox = materialize_event(self._state, append, now=now)
            resulting = decision.previous_version + 1
            outcome = self._outcome(
                write,
                LedgerMutationStatus.APPLIED,
                decision.previous_version,
                resulting,
            )
            put_record(self._state, write.record, version=resulting)
            record_event(self._state, append, recorded, outbox)
            self._state.commands[_command_key(write)] = StoredCommand(
                write.command, write, outcome
            )
            return outcome

    async def append_event(self, append: AtomicEventAppend) -> EventAppendOutcome:
        if type(append) is not AtomicEventAppend:
            raise TypeError("append must be an exact AtomicEventAppend")
        async with self._lock:
            now = _aware("ledger clock", self._clock())
            return append_event_locked(self._state, self._limits, append, now=now)

    async def write_runtime_identity(
        self, identity: RuntimeIdentity, *, expected_generation: int
    ) -> RuntimeIdentityWriteOutcome:
        if type(identity) is not RuntimeIdentity:
            raise TypeError("identity must be an exact RuntimeIdentity")
        _nonnegative("expected_generation", expected_generation)
        async with self._lock:
            now = _aware("ledger clock", self._clock())
            return write_runtime_identity_locked(
                self._state,
                self._limits,
                identity,
                expected_generation=expected_generation,
                now=now,
            )

    async def append_binding(self, binding: CodexBinding) -> BindingWriteOutcome:
        if type(binding) not in {CodexThreadBinding, CodexTurnBinding, CodexItemBinding}:
            raise TypeError("binding must be an exact Codex binding")
        async with self._lock:
            now = _aware("ledger clock", self._clock())
            return append_binding_locked(
                self._state, self._limits, binding, now=now
            )

    async def get_root(self, scope: ExecutionScopeRef) -> ExecutionRootRun | None:
        _scope(scope)
        async with self._lock:
            return self._state.roots.get(scope_key(scope))

    async def get_phase(
        self, scope: ExecutionScopeRef, phase_id: str
    ) -> ExecutionPhase | None:
        return cast(ExecutionPhase | None, await self._get(scope, phase_id, "phase"))

    async def get_work_item(
        self, scope: ExecutionScopeRef, work_item_id: str
    ) -> ExecutionWorkItem | None:
        return cast(
            ExecutionWorkItem | None, await self._get(scope, work_item_id, "work")
        )

    async def get_assignment(
        self, scope: ExecutionScopeRef, assignment_id: str
    ) -> ExecutionAssignment | None:
        return cast(
            ExecutionAssignment | None,
            await self._get(scope, assignment_id, "assignment"),
        )

    async def get_result(
        self, scope: ExecutionScopeRef, result_id: str
    ) -> ExecutionResult | None:
        return cast(ExecutionResult | None, await self._get(scope, result_id, "result"))

    async def get_verification(
        self, scope: ExecutionScopeRef, verification_id: str
    ) -> ExecutionVerification | None:
        return cast(
            ExecutionVerification | None,
            await self._get(scope, verification_id, "verification"),
        )

    async def get_command_outcome(
        self, scope: ExecutionScopeRef, command_id: str
    ) -> LedgerMutationOutcome | None:
        _scope(scope)
        _identifier("command_id", command_id)
        async with self._lock:
            stored = self._state.commands.get((scope_key(scope), command_id))
            return None if stored is None else stored.outcome

    async def get_runtime_identity(
        self, workspace: WorkspaceScopeRef, identity_id: str
    ) -> RuntimeIdentity | None:
        if type(workspace) is not WorkspaceScopeRef:
            raise TypeError("workspace must be an exact WorkspaceScopeRef")
        _identifier("identity_id", identity_id)
        async with self._lock:
            return self._state.identities.get((workspace_key(workspace), identity_id))

    async def list_events(
        self, scope: ExecutionScopeRef, *, after_sequence: int = 0, limit: int = 100
    ) -> tuple[RecordedExecutionEvent, ...]:
        _scope(scope)
        _page(after_sequence, limit)
        async with self._lock:
            return tuple(
                item
                for item in self._state.events.get(scope_key(scope), ())
                if item.sequence > after_sequence
            )[:limit]

    async def list_outbox(
        self, scope: ExecutionScopeRef, *, limit: int = 100
    ) -> tuple[ExecutionOutboxRecord, ...]:
        _scope(scope)
        _page(0, limit)
        key = scope_key(scope)
        async with self._lock:
            values = (
                item for (owner, _), item in self._state.outbox.items() if owner == key
            )
            return tuple(
                sorted(values, key=lambda item: (item.event.sequence, item.id))
            )[:limit]

    async def _get(self, scope: ExecutionScopeRef, item_id: str, kind: str) -> object | None:
        _scope(scope)
        _identifier("aggregate_id", item_id)
        key = aggregate_key(scope, item_id)
        async with self._lock:
            if kind == "phase":
                return self._state.phases.get(key)
            if kind == "work":
                return self._state.work_items.get(key)
            if kind == "assignment":
                return self._state.assignments.get(key)
            if kind == "result":
                return self._state.results.get(key)
            return self._state.verifications.get(key)

    def _replay_outcome(self, write: AtomicLedgerWrite) -> LedgerMutationOutcome | None:
        stored = self._state.commands.get(_command_key(write))
        if stored is None:
            return None
        decision = classify_command_replay(write.command, stored.command)
        if decision is CommandReplayDecision.REPLAY and stored.submitted == write:
            return replace(stored.outcome, status=LedgerMutationStatus.REPLAYED)
        return self._outcome(write, LedgerMutationStatus.CONFLICT, None, None)

    def _store_terminal_command(
        self,
        write: AtomicLedgerWrite,
        status: LedgerMutationStatus,
        previous: int,
    ) -> LedgerMutationOutcome:
        outcome = self._outcome(write, status, previous, None)
        if len(self._state.commands) < self._limits.commands:
            self._state.commands[_command_key(write)] = StoredCommand(
                write.command, write, outcome
            )
        return outcome

    @staticmethod
    def _outcome(
        write: AtomicLedgerWrite,
        status: LedgerMutationStatus,
        previous: int | None,
        resulting: int | None,
    ) -> LedgerMutationOutcome:
        return LedgerMutationOutcome(
            write.command.scope,
            write.command.id,
            write.command.request_digest,
            status,
            write.command.aggregate_kind,
            write.command.aggregate_id,
            previous,
            resulting,
        )


def _command_key(write: AtomicLedgerWrite) -> tuple[tuple[str, str, str], str]:
    return (scope_key(write.command.scope), write.command.id)


def _scope(value: object) -> ExecutionScopeRef:
    if type(value) is not ExecutionScopeRef:
        raise TypeError("scope must be an exact ExecutionScopeRef")
    return value


def _identifier(label: str, value: object) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > 160:
        raise ValueError(f"{label} must be a bounded, non-empty trimmed string")
    return value


def _aware(label: str, value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be an exact timezone-aware datetime")
    return value


def _nonnegative(label: str, value: object) -> int:
    if type(value) is not int or not 0 <= value <= MAX_SIGNED_BIGINT:
        raise ValueError(f"{label} must be a non-negative signed BIGINT")
    return value


def _page(after: object, limit: object) -> None:
    _nonnegative("after_sequence", after)
    if type(limit) is not int or not 1 <= limit <= MAX_LEDGER_PAGE_SIZE:
        raise ValueError(f"limit must be between 1 and {MAX_LEDGER_PAGE_SIZE}")


__all__ = ["MemoryExecutionLedger", "MemoryLedgerLimits"]
