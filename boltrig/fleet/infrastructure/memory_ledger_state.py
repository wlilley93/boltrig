"""Private state container for the atomic in-memory execution ledger."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias, cast

from boltrig.fleet.ports.execution_ledger import (
    AtomicEventAppend,
    AtomicLedgerWrite,
    ExecutionLedgerRecord,
)
from boltrig.models import (
    CodexItemBinding,
    CodexThreadBinding,
    CodexTurnBinding,
    EngineOwner,
    ExecutionAggregateKind,
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
    RecordedExecutionEvent,
    RuntimeIdentity,
    WorkspaceScopeRef,
)

ScopeKey: TypeAlias = tuple[str, str, str]
WorkspaceKey: TypeAlias = tuple[str, str]
AggregateKey: TypeAlias = tuple[ScopeKey, str]
EventIngestionKey: TypeAlias = tuple[ScopeKey, EngineOwner, str]
CommandKey: TypeAlias = tuple[ScopeKey, str]


@dataclass(frozen=True)
class StoredCommand:
    command: LedgerCommand
    submitted: AtomicLedgerWrite
    outcome: LedgerMutationOutcome


@dataclass(frozen=True)
class StoredEventAppend:
    submitted: AtomicEventAppend
    event: RecordedExecutionEvent
    outbox: tuple[ExecutionOutboxRecord, ...]


@dataclass(frozen=True)
class MemoryLedgerLimits:
    """Hard global bounds for the non-evicting in-memory source of truth."""

    roots: int = 256
    records: int = 16_384
    commands: int = 32_768
    events: int = 65_536
    outbox: int = 131_072
    identities: int = 4_096
    bindings: int = 65_536

    def __post_init__(self) -> None:
        for label, value in (
            ("roots", self.roots),
            ("records", self.records),
            ("commands", self.commands),
            ("events", self.events),
            ("outbox", self.outbox),
            ("identities", self.identities),
            ("bindings", self.bindings),
        ):
            if type(value) is not int or value < 1:
                raise ValueError(f"memory ledger {label} limit must be a positive integer")


@dataclass
class MemoryLedgerState:
    roots: dict[ScopeKey, ExecutionRootRun] = field(default_factory=dict)
    phases: dict[AggregateKey, ExecutionPhase] = field(default_factory=dict)
    work_items: dict[AggregateKey, ExecutionWorkItem] = field(default_factory=dict)
    assignments: dict[AggregateKey, ExecutionAssignment] = field(default_factory=dict)
    results: dict[AggregateKey, ExecutionResult] = field(default_factory=dict)
    verifications: dict[AggregateKey, ExecutionVerification] = field(default_factory=dict)
    versions: dict[tuple[ExecutionAggregateKind, AggregateKey], int] = field(
        default_factory=dict
    )
    commands: dict[CommandKey, StoredCommand] = field(default_factory=dict)
    events: dict[ScopeKey, list[RecordedExecutionEvent]] = field(default_factory=dict)
    root_sequences: dict[ScopeKey, int] = field(default_factory=dict)
    events_by_id: dict[tuple[ScopeKey, str], RecordedExecutionEvent] = field(
        default_factory=dict
    )
    events_by_ingestion: dict[EventIngestionKey, RecordedExecutionEvent] = field(
        default_factory=dict
    )
    event_appends: dict[EventIngestionKey, StoredEventAppend] = field(default_factory=dict)
    source_sequences: dict[tuple[ScopeKey, EngineOwner], int] = field(default_factory=dict)
    outbox: dict[tuple[ScopeKey, str], ExecutionOutboxRecord] = field(default_factory=dict)
    outbox_delivery_keys: dict[tuple[ScopeKey, str], str] = field(default_factory=dict)
    identities: dict[tuple[WorkspaceKey, str], RuntimeIdentity] = field(default_factory=dict)
    threads: dict[AggregateKey, CodexThreadBinding] = field(default_factory=dict)
    turns: dict[tuple[ScopeKey, str, str], CodexTurnBinding] = field(default_factory=dict)
    items: dict[tuple[ScopeKey, str, str, str], CodexItemBinding] = field(
        default_factory=dict
    )


def scope_key(scope: ExecutionScopeRef) -> ScopeKey:
    return (scope.tenant_id, scope.workspace_id, scope.root_run_id)


def workspace_key(workspace: WorkspaceScopeRef) -> WorkspaceKey:
    return (workspace.tenant_id, workspace.workspace_id)


def aggregate_key(scope: ExecutionScopeRef, aggregate_id: str) -> AggregateKey:
    return (scope_key(scope), aggregate_id)


def record_kind(record: ExecutionLedgerRecord) -> ExecutionAggregateKind:
    if type(record) is ExecutionRootRun:
        return ExecutionAggregateKind.ROOT_RUN
    if type(record) is ExecutionPhase:
        return ExecutionAggregateKind.PHASE
    if type(record) is ExecutionWorkItem:
        return ExecutionAggregateKind.WORK_ITEM
    if type(record) is ExecutionAssignment:
        return ExecutionAggregateKind.ASSIGNMENT
    if type(record) is ExecutionResult:
        return ExecutionAggregateKind.RESULT
    if type(record) is ExecutionVerification:
        return ExecutionAggregateKind.VERIFICATION
    raise TypeError("unknown execution-ledger record")


def record_id(record: ExecutionLedgerRecord) -> str:
    if type(record) is ExecutionRootRun:
        return record.scope.root_run_id
    return cast(str, getattr(record, "id"))


def get_record(
    state: MemoryLedgerState,
    kind: ExecutionAggregateKind,
    scope: ExecutionScopeRef,
    item_id: str,
) -> ExecutionLedgerRecord | None:
    key = aggregate_key(scope, item_id)
    if kind is ExecutionAggregateKind.ROOT_RUN:
        return state.roots.get(scope_key(scope))
    if kind is ExecutionAggregateKind.PHASE:
        return state.phases.get(key)
    if kind is ExecutionAggregateKind.WORK_ITEM:
        return state.work_items.get(key)
    if kind is ExecutionAggregateKind.ASSIGNMENT:
        return state.assignments.get(key)
    if kind is ExecutionAggregateKind.RESULT:
        return state.results.get(key)
    return state.verifications.get(key)


def get_version(
    state: MemoryLedgerState,
    kind: ExecutionAggregateKind,
    scope: ExecutionScopeRef,
    item_id: str,
) -> int:
    record = get_record(state, kind, scope, item_id)
    if record is None:
        return 0
    version = getattr(record, "version", None)
    if type(version) is int:
        return version
    return state.versions.get((kind, aggregate_key(scope, item_id)), 1)


def put_record(
    state: MemoryLedgerState, record: ExecutionLedgerRecord, *, version: int
) -> None:
    kind = record_kind(record)
    item_id = record_id(record)
    key = aggregate_key(record.scope, item_id)
    if kind is ExecutionAggregateKind.ROOT_RUN:
        state.roots[scope_key(record.scope)] = cast(ExecutionRootRun, record)
    elif kind is ExecutionAggregateKind.PHASE:
        state.phases[key] = cast(ExecutionPhase, record)
    elif kind is ExecutionAggregateKind.WORK_ITEM:
        state.work_items[key] = cast(ExecutionWorkItem, record)
    elif kind is ExecutionAggregateKind.ASSIGNMENT:
        state.assignments[key] = cast(ExecutionAssignment, record)
    elif kind is ExecutionAggregateKind.RESULT:
        state.results[key] = cast(ExecutionResult, record)
    else:
        state.verifications[key] = cast(ExecutionVerification, record)
    state.versions[(kind, key)] = version


def root_for(state: MemoryLedgerState, scope: ExecutionScopeRef) -> ExecutionRootRun | None:
    return state.roots.get(scope_key(scope))


__all__ = [
    "MemoryLedgerState",
    "MemoryLedgerLimits",
    "StoredCommand",
    "StoredEventAppend",
    "aggregate_key",
    "get_record",
    "get_version",
    "put_record",
    "record_id",
    "record_kind",
    "root_for",
    "scope_key",
    "workspace_key",
]
