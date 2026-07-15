"""Fail-closed capacity checks for the bounded in-memory execution ledger."""

from __future__ import annotations

from boltrig.fleet.infrastructure.memory_ledger_state import (
    MemoryLedgerLimits,
    MemoryLedgerState,
    get_record,
    record_id,
    record_kind,
)
from boltrig.fleet.ports.execution_ledger import AtomicEventAppend, AtomicLedgerWrite
from boltrig.models import ExecutionRootRun


def ledger_write_fits(
    state: MemoryLedgerState,
    limits: MemoryLedgerLimits,
    write: AtomicLedgerWrite,
) -> bool:
    """Return whether a new command can be retained without eviction."""

    if len(state.commands) >= limits.commands:
        return False
    existing = get_record(
        state, record_kind(write.record), write.record.scope, record_id(write.record)
    )
    if existing is None:
        if type(write.record) is ExecutionRootRun and len(state.roots) >= limits.roots:
            return False
        if _record_count(state) >= limits.records:
            return False
    return event_append_fits(state, limits, AtomicEventAppend(write.event, write.outbox))


def event_append_fits(
    state: MemoryLedgerState,
    limits: MemoryLedgerLimits,
    append: AtomicEventAppend,
) -> bool:
    if _event_count(state) >= limits.events:
        return False
    return len(state.outbox) + len(append.outbox) <= limits.outbox


def identity_fits(state: MemoryLedgerState, limits: MemoryLedgerLimits) -> bool:
    return len(state.identities) < limits.identities


def binding_fits(state: MemoryLedgerState, limits: MemoryLedgerLimits) -> bool:
    return _binding_count(state) < limits.bindings


def _record_count(state: MemoryLedgerState) -> int:
    return sum(
        len(values)
        for values in (
            state.roots,
            state.phases,
            state.work_items,
            state.assignments,
            state.results,
            state.verifications,
        )
    )


def _event_count(state: MemoryLedgerState) -> int:
    return sum(len(values) for values in state.events.values())


def _binding_count(state: MemoryLedgerState) -> int:
    return len(state.threads) + len(state.turns) + len(state.items)


__all__ = ["binding_fits", "event_append_fits", "identity_fits", "ledger_write_fits"]
