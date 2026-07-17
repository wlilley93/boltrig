"""Rebuild the pure MemoryLedgerState for one scope from durable rows.

The durable adapter owns no business logic. Every mutating call hydrates the
exact state shape the pure memory helpers read, runs those helpers unchanged, and
persists only their known outputs. Hydration is therefore the whole coupling
surface between PostgreSQL and the validated domain.

Aggregate versions come from ``execution_commands``: ``ExecutionResult`` and
``ExecutionVerification`` carry no ``version`` field (and no version column), so
their compare-and-swap version is replayed from the ``resulting_version`` of the
applied commands that produced them, which is exactly what ``put_record`` wrote
into ``state.versions`` in the memory adapter.
"""

from __future__ import annotations

from typing import Any

import asyncpg

from boltrig.fleet.infrastructure.memory_ledger_state import (
    MemoryLedgerState,
    StoredCommand,
    StoredEventAppend,
    aggregate_key,
    put_record,
    scope_key,
    workspace_key,
)
from boltrig.fleet.infrastructure.postgres_ledger_codec import write_from_json
from boltrig.fleet.infrastructure.postgres_ledger_events import (
    row_to_event,
    row_to_identity,
    row_to_intent,
    row_to_item,
    row_to_outbox,
    row_to_thread,
    row_to_turn,
)
from boltrig.fleet.infrastructure.postgres_ledger_records import (
    row_to_assignment,
    row_to_phase,
    row_to_result,
    row_to_root,
    row_to_verification,
    row_to_work,
)
from boltrig.fleet.ports.execution_ledger import AtomicEventAppend
from boltrig.models import (
    ExecutionAggregateKind,
    ExecutionScopeRef,
    LedgerMutationOutcome,
    LedgerMutationStatus,
    RecordedExecutionEvent,
    WorkspaceScopeRef,
)

Row = Any

_SCOPE_WHERE = "tenant_id = $1 AND workspace_id = $2 AND root_run_id = $3"
_RECORD_TABLES = (
    ("execution_root_runs", row_to_root),
    ("execution_phases", row_to_phase),
    ("execution_work_items", row_to_work),
    ("execution_assignments", row_to_assignment),
    ("execution_results", row_to_result),
    ("execution_verifications", row_to_verification),
)


async def lock_scope(conn: asyncpg.Connection, scope: ExecutionScopeRef) -> None:
    """Serialize every mutation for one root run, exactly as the memory lock does.

    The workspace lock is taken first and in shared mode so identity revocation
    (which takes it exclusively) cannot interleave with a commit that validates
    against those identities, while commits across a workspace stay concurrent.
    Consistent ordering keeps the pair deadlock-free.
    """

    await _lock_workspace(conn, scope.workspace, exclusive=False)
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtext($1))", "\x1f".join(scope_key(scope))
    )


async def lock_workspace_exclusive(
    conn: asyncpg.Connection, workspace: WorkspaceScopeRef
) -> None:
    await _lock_workspace(conn, workspace, exclusive=True)


async def _lock_workspace(
    conn: asyncpg.Connection, workspace: WorkspaceScopeRef, *, exclusive: bool
) -> None:
    function = "pg_advisory_xact_lock" if exclusive else "pg_advisory_xact_lock_shared"
    await conn.execute(
        f"SELECT {function}(hashtext($1))", "\x1f".join(workspace_key(workspace))
    )


async def hydrate(conn: asyncpg.Connection, scope: ExecutionScopeRef) -> MemoryLedgerState:
    """Load every row the pure helpers may read for this scope."""

    state = MemoryLedgerState()
    await _load_records(conn, scope, state)
    await _load_commands(conn, scope, state)
    events = await _load_events(conn, scope, state)
    await _load_outbox(conn, scope, state, events)
    await hydrate_identities(conn, scope.workspace, state)
    await _load_bindings(conn, scope, state)
    return state


async def hydrate_identities(
    conn: asyncpg.Connection, workspace: WorkspaceScopeRef, state: MemoryLedgerState
) -> MemoryLedgerState:
    rows = await conn.fetch(
        "SELECT * FROM runtime_identities WHERE tenant_id = $1 AND workspace_id = $2",
        workspace.tenant_id,
        workspace.workspace_id,
    )
    key = workspace_key(workspace)
    for row in rows:
        state.identities[(key, row["id"])] = row_to_identity(row)
    return state


async def _load_records(
    conn: asyncpg.Connection, scope: ExecutionScopeRef, state: MemoryLedgerState
) -> None:
    """Replay the rows through ``put_record``, the same writer the memory adapter uses.

    Records that carry their own ``version`` seed ``state.versions`` from it;
    results and verifications have none and are corrected by ``_load_commands``,
    which runs next and takes the applied commands' ``resulting_version``.
    """

    for table, mapper in _RECORD_TABLES:
        rows = await conn.fetch(
            f"SELECT * FROM {table} WHERE {_SCOPE_WHERE}", *scope_key(scope)
        )
        for row in rows:
            record = mapper(row)
            put_record(state, record, version=getattr(record, "version", 0))


async def _load_commands(
    conn: asyncpg.Connection, scope: ExecutionScopeRef, state: MemoryLedgerState
) -> None:
    rows = await conn.fetch(
        f"SELECT * FROM execution_commands WHERE {_SCOPE_WHERE}", *scope_key(scope)
    )
    key = scope_key(scope)
    for row in rows:
        submitted = write_from_json(row["submitted"])
        kind = ExecutionAggregateKind(row["aggregate_kind"])
        outcome = LedgerMutationOutcome(
            scope,
            row["command_id"],
            row["request_digest"],
            LedgerMutationStatus(row["status"]),
            kind,
            row["aggregate_id"],
            row["previous_version"],
            row["resulting_version"],
        )
        state.commands[(key, row["command_id"])] = StoredCommand(
            submitted.command, submitted, outcome
        )
        version = row["resulting_version"]
        if outcome.status is LedgerMutationStatus.APPLIED and version is not None:
            slot = (kind, aggregate_key(scope, row["aggregate_id"]))
            state.versions[slot] = max(state.versions.get(slot, 0), version)


async def _load_events(
    conn: asyncpg.Connection, scope: ExecutionScopeRef, state: MemoryLedgerState
) -> dict[int, RecordedExecutionEvent]:
    rows = await conn.fetch(
        f"SELECT * FROM execution_events WHERE {_SCOPE_WHERE} ORDER BY sequence",
        *scope_key(scope),
    )
    key = scope_key(scope)
    events: dict[int, RecordedExecutionEvent] = {}
    for row in rows:
        event = row_to_event(row)
        events[event.sequence] = event
        state.events.setdefault(key, []).append(event)
        state.root_sequences[key] = event.sequence
        state.events_by_id[(key, event.pending.id)] = event
        ingestion = (key, event.pending.source_owner, event.pending.ingestion_idempotency_key)
        state.events_by_ingestion[ingestion] = event
        if event.pending.source_sequence is not None:
            state.source_sequences[(key, event.pending.source_owner)] = (
                event.pending.source_sequence
            )
    return events


async def _load_outbox(
    conn: asyncpg.Connection,
    scope: ExecutionScopeRef,
    state: MemoryLedgerState,
    events: dict[int, RecordedExecutionEvent],
) -> None:
    rows = await conn.fetch(
        f"SELECT * FROM execution_outbox WHERE {_SCOPE_WHERE}", *scope_key(scope)
    )
    key = scope_key(scope)
    grouped: dict[int, list[Row]] = {}
    for row in rows:
        event = events[row["event_sequence"]]
        record = row_to_outbox(row, event)
        state.outbox[(key, record.id)] = record
        state.outbox_delivery_keys[(key, record.delivery_key)] = record.id
        grouped.setdefault(event.sequence, []).append(row)
    for sequence, event in events.items():
        members = sorted(grouped.get(sequence, []), key=lambda item: item["intent_ordinal"])
        if not members:
            continue
        ingestion = (key, event.pending.source_owner, event.pending.ingestion_idempotency_key)
        state.event_appends[ingestion] = _stored_append(event, members)


def _stored_append(event: RecordedExecutionEvent, rows: list[Row]) -> StoredEventAppend:
    """Rebuild the submitted append exactly as it was given to the store.

    Every field of every intent has its own column, and ``intent_ordinal`` restores
    the submitted tuple's order, so this is the caller's original append rather
    than an inference from the materialized rows. The pure ``event_replay`` can
    therefore compare it directly and reach the memory adapter's answer.
    """

    intents = tuple(row_to_intent(row) for row in rows)
    outbox = tuple(row_to_outbox(row, event) for row in rows)
    return StoredEventAppend(AtomicEventAppend(event.pending, intents), event, outbox)


async def _load_bindings(
    conn: asyncpg.Connection, scope: ExecutionScopeRef, state: MemoryLedgerState
) -> None:
    key = scope_key(scope)
    threads = await conn.fetch(
        f"SELECT * FROM codex_thread_bindings WHERE {_SCOPE_WHERE}", *key
    )
    for row in threads:
        state.threads[(key, row["thread_id"])] = row_to_thread(row)
    turns = await conn.fetch(
        f"SELECT * FROM codex_turn_bindings WHERE {_SCOPE_WHERE}", *key
    )
    for row in turns:
        thread = state.threads[(key, row["thread_id"])]
        state.turns[(key, row["thread_id"], row["turn_id"])] = row_to_turn(row, thread)
    items = await conn.fetch(
        f"SELECT * FROM codex_item_bindings WHERE {_SCOPE_WHERE}", *key
    )
    for row in items:
        turn = state.turns[(key, row["thread_id"], row["turn_id"])]
        state.items[(key, row["thread_id"], row["turn_id"], row["item_id"])] = row_to_item(
            row, turn
        )


__all__ = [
    "hydrate",
    "hydrate_identities",
    "lock_scope",
    "lock_workspace_exclusive",
]
