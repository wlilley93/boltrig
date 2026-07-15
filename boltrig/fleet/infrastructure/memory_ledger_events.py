"""Normalized event and transactional-outbox operations for the memory ledger."""

from __future__ import annotations

from datetime import datetime

from boltrig.fleet.infrastructure.memory_ledger_capacity import event_append_fits
from boltrig.fleet.infrastructure.memory_ledger_state import (
    MemoryLedgerLimits,
    MemoryLedgerState,
    StoredEventAppend,
    get_record,
    scope_key,
)
from boltrig.fleet.ports.execution_ledger import (
    AppendStatus,
    AtomicEventAppend,
    EventAppendOutcome,
)
from boltrig.models import (
    EngineOwner,
    ExecutionEventKind,
    ExecutionOutboxRecord,
    LedgerMutationStatus,
    RecordedExecutionEvent,
)
from boltrig.models.execution_scope import MAX_SIGNED_BIGINT


def append_event_locked(
    state: MemoryLedgerState,
    limits: MemoryLedgerLimits,
    append: AtomicEventAppend,
    *,
    now: datetime,
) -> EventAppendOutcome:
    replay = event_replay(state, append)
    if replay is not None:
        return replay
    if not standalone_event_hierarchy(state, append):
        return EventAppendOutcome(AppendStatus.NOT_FOUND, None)
    status = event_preflight(state, append)
    if status is not None:
        return EventAppendOutcome(_append_status(status), None)
    if (
        append.event.occurred_at > now
        or any(item.available_at < append.event.occurred_at for item in append.outbox)
        or any(
            item.delivery_key == append.event.ingestion_idempotency_key
            for item in append.outbox
        )
        or not event_append_fits(state, limits, append)
    ):
        return EventAppendOutcome(AppendStatus.REJECTED, None)
    recorded, outbox = materialize_event(state, append, now=now)
    record_event(state, append, recorded, outbox)
    return EventAppendOutcome(AppendStatus.INSERTED, recorded, outbox)


def event_preflight(
    state: MemoryLedgerState, append: AtomicEventAppend
) -> LedgerMutationStatus | None:
    event = append.event
    key = scope_key(event.scope)
    ingestion = (key, event.source_owner, event.ingestion_idempotency_key)
    if (key, event.id) in state.events_by_id or ingestion in state.events_by_ingestion:
        return LedgerMutationStatus.CONFLICT
    if event.source_sequence is not None:
        previous = state.source_sequences.get((key, event.source_owner), -1)
        if event.source_sequence <= previous:
            return LedgerMutationStatus.REJECTED
    if any((key, item.id) in state.outbox for item in append.outbox):
        return LedgerMutationStatus.CONFLICT
    if any((key, item.delivery_key) in state.outbox_delivery_keys for item in append.outbox):
        return LedgerMutationStatus.CONFLICT
    return None


def materialize_event(
    state: MemoryLedgerState,
    append: AtomicEventAppend,
    *,
    now: datetime,
) -> tuple[RecordedExecutionEvent, tuple[ExecutionOutboxRecord, ...]]:
    pending = append.event
    key = scope_key(pending.scope)
    sequence = state.root_sequences.get(key, 0) + 1
    if sequence > MAX_SIGNED_BIGINT:
        raise OverflowError("root event sequence exhausted signed BIGINT")
    recorded = RecordedExecutionEvent(pending.scope, pending, sequence, now)
    outbox = tuple(
        ExecutionOutboxRecord(
            pending.scope,
            item.id,
            recorded,
            item.destination,
            item.delivery_key,
            created_at=now,
            available_at=max(item.available_at, now),
        )
        for item in append.outbox
    )
    return recorded, outbox


def record_event(
    state: MemoryLedgerState,
    append: AtomicEventAppend,
    event: RecordedExecutionEvent,
    outbox: tuple[ExecutionOutboxRecord, ...],
) -> None:
    key = scope_key(event.scope)
    state.events.setdefault(key, []).append(event)
    state.root_sequences[key] = event.sequence
    state.events_by_id[(key, event.pending.id)] = event
    ingestion = (key, event.pending.source_owner, event.pending.ingestion_idempotency_key)
    state.events_by_ingestion[ingestion] = event
    state.event_appends[ingestion] = StoredEventAppend(append, event, outbox)
    if event.pending.source_sequence is not None:
        state.source_sequences[(key, event.pending.source_owner)] = event.pending.source_sequence
    for item in outbox:
        state.outbox[(key, item.id)] = item
        state.outbox_delivery_keys[(key, item.delivery_key)] = item.id


def event_replay(
    state: MemoryLedgerState, append: AtomicEventAppend
) -> EventAppendOutcome | None:
    event = append.event
    key = scope_key(event.scope)
    stored = state.event_appends.get(
        (key, event.source_owner, event.ingestion_idempotency_key)
    )
    if stored is None:
        return None
    if stored.submitted != append:
        return EventAppendOutcome(AppendStatus.CONFLICT, None)
    return EventAppendOutcome(AppendStatus.REPLAYED, stored.event, stored.outbox)


def standalone_event_hierarchy(
    state: MemoryLedgerState, append: AtomicEventAppend
) -> bool:
    event = append.event
    if event.source_owner is not EngineOwner.CODEX or event.causation_command_id is not None:
        return False
    if event.kind is not ExecutionEventKind.RUNTIME_OBSERVED:
        return False
    return get_record(state, event.aggregate_kind, event.scope, event.aggregate_id) is not None


def _append_status(status: LedgerMutationStatus) -> AppendStatus:
    return {
        LedgerMutationStatus.CONFLICT: AppendStatus.CONFLICT,
        LedgerMutationStatus.REJECTED: AppendStatus.REJECTED,
        LedgerMutationStatus.NOT_FOUND: AppendStatus.NOT_FOUND,
        LedgerMutationStatus.APPLIED: AppendStatus.INSERTED,
        LedgerMutationStatus.REPLAYED: AppendStatus.REPLAYED,
    }[status]


__all__ = [
    "append_event_locked",
    "event_preflight",
    "materialize_event",
    "record_event",
]
