"""Direct SELECT reads for the durable execution ledger.

Reads take no lock: each returns one committed snapshot reconstructed straight
from its rows, which is what the memory adapter's lock-and-copy read gives the
caller too.
"""

from __future__ import annotations

from typing import Any

import asyncpg

from boltrig.fleet.infrastructure.postgres_ledger_events import (
    row_to_event,
    row_to_identity,
    row_to_outbox,
)
from boltrig.fleet.infrastructure.postgres_ledger_records import (
    row_to_assignment,
    row_to_phase,
    row_to_result,
    row_to_root,
    row_to_verification,
    row_to_work,
)
from boltrig.fleet.infrastructure.postgres_ledger_codec import write_from_json
from boltrig.models import (
    ExecutionAggregateKind,
    ExecutionOutboxRecord,
    ExecutionScopeRef,
    LedgerMutationOutcome,
    LedgerMutationStatus,
    RecordedExecutionEvent,
    RuntimeIdentity,
    WorkspaceScopeRef,
)

_SCOPE_WHERE = "tenant_id = $1 AND workspace_id = $2 AND root_run_id = $3"

AGGREGATE_TABLES: dict[ExecutionAggregateKind, tuple[str, Any]] = {
    ExecutionAggregateKind.PHASE: ("execution_phases", row_to_phase),
    ExecutionAggregateKind.WORK_ITEM: ("execution_work_items", row_to_work),
    ExecutionAggregateKind.ASSIGNMENT: ("execution_assignments", row_to_assignment),
    ExecutionAggregateKind.RESULT: ("execution_results", row_to_result),
    ExecutionAggregateKind.VERIFICATION: ("execution_verifications", row_to_verification),
}


def _scope_args(scope: ExecutionScopeRef) -> tuple[str, str, str]:
    return (scope.tenant_id, scope.workspace_id, scope.root_run_id)


async def fetch_root(conn: asyncpg.Connection, scope: ExecutionScopeRef) -> Any:
    row = await conn.fetchrow(
        f"SELECT * FROM execution_root_runs WHERE {_SCOPE_WHERE}", *_scope_args(scope)
    )
    return None if row is None else row_to_root(row)


async def fetch_aggregate(
    conn: asyncpg.Connection,
    scope: ExecutionScopeRef,
    item_id: str,
    kind: ExecutionAggregateKind,
) -> Any:
    table, mapper = AGGREGATE_TABLES[kind]
    row = await conn.fetchrow(
        f"SELECT * FROM {table} WHERE {_SCOPE_WHERE} AND id = $4",
        *_scope_args(scope),
        item_id,
    )
    return None if row is None else mapper(row)


async def fetch_command_outcome(
    conn: asyncpg.Connection, scope: ExecutionScopeRef, command_id: str
) -> LedgerMutationOutcome | None:
    row = await conn.fetchrow(
        f"SELECT * FROM execution_commands WHERE {_SCOPE_WHERE} AND command_id = $4",
        *_scope_args(scope),
        command_id,
    )
    if row is None:
        return None
    return LedgerMutationOutcome(
        scope,
        row["command_id"],
        row["request_digest"],
        LedgerMutationStatus(row["status"]),
        ExecutionAggregateKind(row["aggregate_kind"]),
        row["aggregate_id"],
        row["previous_version"],
        row["resulting_version"],
    )


async def fetch_stored_write(
    conn: asyncpg.Connection, scope: ExecutionScopeRef, command_id: str
) -> Any:
    row = await conn.fetchrow(
        "SELECT submitted FROM execution_commands "
        f"WHERE {_SCOPE_WHERE} AND command_id = $4",
        *_scope_args(scope),
        command_id,
    )
    return None if row is None else write_from_json(row["submitted"])


async def fetch_identity(
    conn: asyncpg.Connection, workspace: WorkspaceScopeRef, identity_id: str
) -> RuntimeIdentity | None:
    row = await conn.fetchrow(
        "SELECT * FROM runtime_identities "
        "WHERE tenant_id = $1 AND workspace_id = $2 AND id = $3",
        workspace.tenant_id,
        workspace.workspace_id,
        identity_id,
    )
    return None if row is None else row_to_identity(row)


async def fetch_events(
    conn: asyncpg.Connection, scope: ExecutionScopeRef, *, after_sequence: int, limit: int
) -> tuple[RecordedExecutionEvent, ...]:
    rows = await conn.fetch(
        f"SELECT * FROM execution_events WHERE {_SCOPE_WHERE} AND sequence > $4 "
        "ORDER BY sequence LIMIT $5",
        *_scope_args(scope),
        after_sequence,
        limit,
    )
    return tuple(row_to_event(row) for row in rows)


async def fetch_outbox(
    conn: asyncpg.Connection, scope: ExecutionScopeRef, *, limit: int
) -> tuple[ExecutionOutboxRecord, ...]:
    rows = await conn.fetch(
        f"SELECT * FROM execution_outbox WHERE {_SCOPE_WHERE} "
        "ORDER BY event_sequence, id LIMIT $4",
        *_scope_args(scope),
        limit,
    )
    if not rows:
        return ()
    events = await conn.fetch(
        f"SELECT * FROM execution_events WHERE {_SCOPE_WHERE} "
        "AND sequence = ANY($4::bigint[])",
        *_scope_args(scope),
        sorted({row["event_sequence"] for row in rows}),
    )
    by_sequence = {row["sequence"]: row_to_event(row) for row in events}
    return tuple(row_to_outbox(row, by_sequence[row["event_sequence"]]) for row in rows)


__all__ = [
    "AGGREGATE_TABLES",
    "fetch_aggregate",
    "fetch_command_outcome",
    "fetch_events",
    "fetch_identity",
    "fetch_outbox",
    "fetch_root",
    "fetch_stored_write",
]
