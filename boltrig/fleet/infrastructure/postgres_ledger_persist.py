"""Persist the known outputs of the pure execution-ledger step.

Nothing here decides anything. The pure helpers have already run over a hydrated
state and produced a decision; these functions write exactly what that decision
produced, inside the caller's transaction and advisory lock:

* applied      - upsert the record at its resulting version, insert the event,
                 its outbox rows, and the command row
* terminal     - insert the command row only
* replayed     - nothing at all (the caller returns before reaching here)

Records are upserted because a compare-and-swap revision replaces the row at a
new version; events, outbox rows, commands, and bindings are insert-only, and the
per-scope advisory lock makes a plain INSERT safe for each.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import asyncpg

from boltrig.fleet.infrastructure.memory_ledger_state import record_kind
from boltrig.fleet.infrastructure.postgres_ledger_codec import write_to_json
from boltrig.fleet.infrastructure.postgres_ledger_events import (
    EVENT_COLS,
    IDENTITY_COLS,
    ITEM_COLS,
    OUTBOX_COLS,
    THREAD_COLS,
    TURN_COLS,
    event_values,
    identity_values,
    item_values,
    outbox_values,
    thread_values,
    turn_values,
)
from boltrig.fleet.infrastructure.postgres_ledger_records import (
    ASSIGNMENT_COLS,
    PHASE_COLS,
    RESULT_COLS,
    ROOT_COLS,
    VERIFICATION_COLS,
    WORK_COLS,
    assignment_values,
    phase_values,
    result_values,
    root_values,
    verification_values,
    work_values,
)
from boltrig.fleet.ports.execution_ledger import (
    AtomicLedgerWrite,
    CodexBinding,
    ExecutionLedgerRecord,
    OutboxIntent,
)
from boltrig.models import (
    CodexItemBinding,
    CodexThreadBinding,
    CodexTurnBinding,
    ExecutionAggregateKind,
    ExecutionOutboxRecord,
    LedgerMutationOutcome,
    RecordedExecutionEvent,
    RuntimeIdentity,
)

COMMAND_COLS = [
    "tenant_id", "workspace_id", "root_run_id", "command_id", "request_digest",
    "aggregate_kind", "aggregate_id", "status", "previous_version",
    "resulting_version", "submitted", "recorded_at",
]

_RECORD_TARGETS: dict[ExecutionAggregateKind, tuple[str, list[str], int]] = {
    ExecutionAggregateKind.ROOT_RUN: ("execution_root_runs", ROOT_COLS, 3),
    ExecutionAggregateKind.PHASE: ("execution_phases", PHASE_COLS, 4),
    ExecutionAggregateKind.WORK_ITEM: ("execution_work_items", WORK_COLS, 4),
    ExecutionAggregateKind.ASSIGNMENT: ("execution_assignments", ASSIGNMENT_COLS, 4),
    ExecutionAggregateKind.RESULT: ("execution_results", RESULT_COLS, 4),
    ExecutionAggregateKind.VERIFICATION: ("execution_verifications", VERIFICATION_COLS, 4),
}


def _insert(table: str, cols: list[str]) -> str:
    placeholders = ", ".join(f"${index}" for index in range(1, len(cols) + 1))
    return f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"


def _upsert(table: str, cols: list[str], keys: int) -> str:
    updates = ", ".join(f"{name} = EXCLUDED.{name}" for name in cols[keys:])
    conflict = ", ".join(cols[:keys])
    return f"{_insert(table, cols)} ON CONFLICT ({conflict}) DO UPDATE SET {updates}"


_RECORD_VALUES: dict[ExecutionAggregateKind, Any] = {
    ExecutionAggregateKind.ROOT_RUN: root_values,
    ExecutionAggregateKind.PHASE: phase_values,
    ExecutionAggregateKind.WORK_ITEM: work_values,
    ExecutionAggregateKind.ASSIGNMENT: assignment_values,
    ExecutionAggregateKind.RESULT: result_values,
    ExecutionAggregateKind.VERIFICATION: verification_values,
}


async def upsert_record(conn: asyncpg.Connection, record: ExecutionLedgerRecord) -> None:
    kind = record_kind(record)
    table, cols, keys = _RECORD_TARGETS[kind]
    await conn.execute(_upsert(table, cols, keys), *_RECORD_VALUES[kind](record))


async def insert_event(conn: asyncpg.Connection, event: RecordedExecutionEvent) -> None:
    await conn.execute(_insert("execution_events", EVENT_COLS), *event_values(event))


async def insert_outbox(
    conn: asyncpg.Connection,
    outbox: tuple[ExecutionOutboxRecord, ...],
    intents: tuple[OutboxIntent, ...],
) -> None:
    """Write each materialized record beside the intent that produced it.

    ``materialize_event`` maps intents to records one-for-one, and intent ids are
    unique within an append, so pairing by id recovers each record's requested
    ``available_at`` and its position in the submitted tuple.
    """

    positions = {intent.id: index for index, intent in enumerate(intents)}
    by_id = {intent.id: intent for intent in intents}
    statement = _insert("execution_outbox", OUTBOX_COLS)
    for record in outbox:
        intent = by_id[record.id]
        await conn.execute(
            statement, *outbox_values(record, intent, positions[record.id])
        )


async def insert_command(
    conn: asyncpg.Connection,
    write: AtomicLedgerWrite,
    outcome: LedgerMutationOutcome,
    *,
    now: datetime,
) -> None:
    scope = outcome.scope
    await conn.execute(
        _insert("execution_commands", COMMAND_COLS),
        scope.tenant_id,
        scope.workspace_id,
        scope.root_run_id,
        outcome.command_id,
        outcome.request_digest,
        outcome.aggregate_kind.value,
        outcome.aggregate_id,
        outcome.status.value,
        outcome.previous_version,
        outcome.resulting_version,
        write_to_json(write),
        now,
    )


async def upsert_identity(
    conn: asyncpg.Connection, identity: RuntimeIdentity, *, now: datetime
) -> None:
    await conn.execute(
        _upsert("runtime_identities", IDENTITY_COLS, 3),
        *identity_values(identity, now=now),
    )


async def insert_binding(conn: asyncpg.Connection, binding: CodexBinding) -> None:
    table, cols, values = _binding_target(binding)
    await conn.execute(_insert(table, cols), *values)


def _binding_target(binding: CodexBinding) -> tuple[str, list[str], tuple[object, ...]]:
    if type(binding) is CodexThreadBinding:
        return ("codex_thread_bindings", THREAD_COLS, thread_values(binding))
    if type(binding) is CodexTurnBinding:
        return ("codex_turn_bindings", TURN_COLS, turn_values(binding))
    if type(binding) is CodexItemBinding:
        return ("codex_item_bindings", ITEM_COLS, item_values(binding))
    raise TypeError("binding must be an exact Codex binding")


__all__ = [
    "COMMAND_COLS",
    "insert_binding",
    "insert_command",
    "insert_event",
    "insert_outbox",
    "upsert_identity",
    "upsert_record",
]
