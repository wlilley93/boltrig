"""Canonical execution-ledger persistence boundary.

The ledger is the source of truth.  Boards, timelines, and other UI views are
projections over this port and must never mutate execution state directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol, TypeAlias

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
    LedgerCommand,
    LedgerMutationOutcome,
    PendingExecutionEvent,
    RecordedExecutionEvent,
    RuntimeIdentity,
    WorkspaceScopeRef,
)

ExecutionLedgerRecord: TypeAlias = (
    ExecutionRootRun
    | ExecutionPhase
    | ExecutionWorkItem
    | ExecutionAssignment
    | ExecutionResult
    | ExecutionVerification
)
CodexBinding: TypeAlias = CodexThreadBinding | CodexTurnBinding | CodexItemBinding

MAX_OUTBOX_DESTINATIONS = 8
MAX_LEDGER_PAGE_SIZE = 256


class AppendStatus(str, Enum):
    INSERTED = "inserted"
    REPLAYED = "replayed"
    CONFLICT = "conflict"
    REJECTED = "rejected"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class OutboxIntent:
    """Delivery metadata completed by the store after assigning event sequence."""

    id: str
    destination: str
    delivery_key: str
    available_at: datetime

    def __post_init__(self) -> None:
        for label, value in (
            ("outbox id", self.id),
            ("outbox destination", self.destination),
            ("outbox delivery_key", self.delivery_key),
        ):
            _identifier(label, value)
        _aware("outbox available_at", self.available_at)


@dataclass(frozen=True)
class AtomicLedgerWrite:
    """One command, state revision, event, and its delivery intents."""

    command: LedgerCommand
    record: ExecutionLedgerRecord
    event: PendingExecutionEvent
    outbox: tuple[OutboxIntent, ...]

    def __post_init__(self) -> None:
        if type(self.command) is not LedgerCommand:
            raise TypeError("command must be an exact LedgerCommand")
        if type(self.record) not in _LEDGER_RECORD_TYPES:
            raise TypeError("record must be an exact canonical execution record")
        if type(self.event) is not PendingExecutionEvent:
            raise TypeError("event must be an exact PendingExecutionEvent")
        _outbox_tuple(self.outbox)
        if not (self.command.scope == self.record.scope == self.event.scope):
            raise ValueError("atomic ledger write scopes differ")


@dataclass(frozen=True)
class AtomicEventAppend:
    """A normalized observation and outbox writes committed as one unit."""

    event: PendingExecutionEvent
    outbox: tuple[OutboxIntent, ...]

    def __post_init__(self) -> None:
        if type(self.event) is not PendingExecutionEvent:
            raise TypeError("event must be an exact PendingExecutionEvent")
        _outbox_tuple(self.outbox)


@dataclass(frozen=True)
class EventAppendOutcome:
    status: AppendStatus
    event: RecordedExecutionEvent | None
    outbox: tuple[ExecutionOutboxRecord, ...] = ()

    def __post_init__(self) -> None:
        if type(self.status) is not AppendStatus:
            raise TypeError("status must be an exact AppendStatus")
        if self.event is not None and type(self.event) is not RecordedExecutionEvent:
            raise TypeError("event must be an exact RecordedExecutionEvent")
        if type(self.outbox) is not tuple or any(
            type(item) is not ExecutionOutboxRecord for item in self.outbox
        ):
            raise TypeError("outbox must contain exact ExecutionOutboxRecord values")
        successful = self.status in {AppendStatus.INSERTED, AppendStatus.REPLAYED}
        if successful != (self.event is not None):
            raise ValueError("event append status and durable event disagree")


@dataclass(frozen=True)
class RuntimeIdentityWriteOutcome:
    status: AppendStatus
    identity: RuntimeIdentity | None

    def __post_init__(self) -> None:
        if type(self.status) is not AppendStatus:
            raise TypeError("status must be an exact AppendStatus")
        if self.identity is not None and type(self.identity) is not RuntimeIdentity:
            raise TypeError("identity must be an exact RuntimeIdentity")


@dataclass(frozen=True)
class BindingWriteOutcome:
    status: AppendStatus
    binding: CodexBinding | None

    def __post_init__(self) -> None:
        if type(self.status) is not AppendStatus:
            raise TypeError("status must be an exact AppendStatus")
        if self.binding is not None and type(self.binding) not in _BINDING_TYPES:
            raise TypeError("binding must be an exact Codex binding")


class ExecutionLedgerStore(Protocol):
    """Atomic tenant-scoped canonical ledger operations."""

    async def commit(self, write: AtomicLedgerWrite) -> LedgerMutationOutcome: ...

    async def append_event(self, append: AtomicEventAppend) -> EventAppendOutcome: ...

    async def write_runtime_identity(
        self, identity: RuntimeIdentity, *, expected_generation: int
    ) -> RuntimeIdentityWriteOutcome: ...

    async def append_binding(self, binding: CodexBinding) -> BindingWriteOutcome: ...

    async def get_root(self, scope: ExecutionScopeRef) -> ExecutionRootRun | None: ...

    async def get_phase(
        self, scope: ExecutionScopeRef, phase_id: str
    ) -> ExecutionPhase | None: ...

    async def get_work_item(
        self, scope: ExecutionScopeRef, work_item_id: str
    ) -> ExecutionWorkItem | None: ...

    async def get_assignment(
        self, scope: ExecutionScopeRef, assignment_id: str
    ) -> ExecutionAssignment | None: ...

    async def get_result(
        self, scope: ExecutionScopeRef, result_id: str
    ) -> ExecutionResult | None: ...

    async def get_verification(
        self, scope: ExecutionScopeRef, verification_id: str
    ) -> ExecutionVerification | None: ...

    async def get_command_outcome(
        self, scope: ExecutionScopeRef, command_id: str
    ) -> LedgerMutationOutcome | None: ...

    async def get_runtime_identity(
        self, workspace: WorkspaceScopeRef, identity_id: str
    ) -> RuntimeIdentity | None: ...

    async def list_events(
        self, scope: ExecutionScopeRef, *, after_sequence: int = 0, limit: int = 100
    ) -> tuple[RecordedExecutionEvent, ...]: ...

    async def list_outbox(
        self, scope: ExecutionScopeRef, *, limit: int = 100
    ) -> tuple[ExecutionOutboxRecord, ...]: ...


_LEDGER_RECORD_TYPES = (
    ExecutionRootRun,
    ExecutionPhase,
    ExecutionWorkItem,
    ExecutionAssignment,
    ExecutionResult,
    ExecutionVerification,
)
_BINDING_TYPES = (CodexThreadBinding, CodexTurnBinding, CodexItemBinding)


def _identifier(label: str, value: object) -> str:
    if type(value) is not str:
        raise TypeError(f"{label} must be an exact string")
    if not value or value != value.strip() or len(value) > 160:
        raise ValueError(f"{label} must be a bounded, trimmed identifier")
    if any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in value):
        raise ValueError(f"{label} contains a control character")
    return value


def _aware(label: str, value: object) -> datetime:
    if type(value) is not datetime:
        raise TypeError(f"{label} must be an exact datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value


def _outbox_tuple(values: object) -> None:
    if type(values) is not tuple:
        raise TypeError("outbox intents must be an immutable tuple")
    if not values or len(values) > MAX_OUTBOX_DESTINATIONS:
        raise ValueError("outbox intents must contain one to eight destinations")
    if any(type(value) is not OutboxIntent for value in values):
        raise TypeError("outbox intents must contain exact OutboxIntent values")
    intents = values
    if len({item.id for item in intents}) != len(intents):
        raise ValueError("outbox ids must be unique in one atomic write")
    if len({item.delivery_key for item in intents}) != len(intents):
        raise ValueError("outbox delivery keys must be unique in one atomic write")


__all__ = [
    "AppendStatus",
    "AtomicEventAppend",
    "AtomicLedgerWrite",
    "BindingWriteOutcome",
    "CodexBinding",
    "EventAppendOutcome",
    "ExecutionLedgerRecord",
    "ExecutionLedgerStore",
    "MAX_LEDGER_PAGE_SIZE",
    "OutboxIntent",
    "RuntimeIdentityWriteOutcome",
]
