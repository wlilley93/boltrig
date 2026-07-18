"""Durable asyncpg adapter for the canonical execution ledger."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import Any, cast

import asyncpg

from boltrig.fleet.infrastructure.memory_ledger_events import (
    append_event_locked,
    event_preflight,
    materialize_event,
)
from boltrig.fleet.infrastructure.memory_ledger_runtime import (
    append_binding_locked,
    write_runtime_identity_locked,
)
from boltrig.fleet.infrastructure.memory_ledger_state import (
    MemoryLedgerLimits,
    MemoryLedgerState,
)
from boltrig.fleet.infrastructure.memory_ledger_validation import validate_write
from boltrig.fleet.infrastructure.postgres_ledger_hydrate import (
    hydrate,
    hydrate_identities,
    lock_scope,
    lock_workspace_exclusive,
)
from boltrig.fleet.infrastructure.postgres_ledger_persist import (
    insert_binding,
    insert_command,
    insert_event,
    insert_outbox,
    upsert_identity,
    upsert_record,
)
from boltrig.fleet.infrastructure.postgres_ledger_reads import (
    fetch_aggregate,
    fetch_command_outcome,
    fetch_events,
    fetch_identity,
    fetch_outbox,
    fetch_root,
    fetch_stored_write,
)
from boltrig.fleet.ports.execution_ledger import (
    MAX_LEDGER_PAGE_SIZE,
    AppendStatus,
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
    ExecutionAggregateKind,
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

# The durable ledger is unbounded: bounded-record backpressure is a property of
# the in-memory adapter only. Passing effectively-infinite limits keeps the shared
# pure helpers' capacity branches unreachable without forking them.
_UNBOUNDED = MemoryLedgerLimits(
    roots=MAX_SIGNED_BIGINT,
    records=MAX_SIGNED_BIGINT,
    commands=MAX_SIGNED_BIGINT,
    events=MAX_SIGNED_BIGINT,
    outbox=MAX_SIGNED_BIGINT,
    identities=MAX_SIGNED_BIGINT,
    bindings=MAX_SIGNED_BIGINT,
)


class PostgresExecutionLedger:
    """Durable execution ledger backed by PostgreSQL.

    Owns no business logic. Every mutation runs inside one transaction holding a
    per-scope transactional advisory lock, and inside that lock it hydrates the
    scope's rows into the same ``MemoryLedgerState`` the in-memory adapter keeps
    in process, runs the same pure validation/materialisation helpers, and
    persists only their outputs. Competing writers for one root run therefore
    serialize exactly as the single-process lock does, and the two adapters agree
    on status, version, sequence, and timestamp by construction.

    All persisted timestamps come from the injected ``clock``, never from the
    database's ``now()``, so the ledger's time is the caller's time.
    """

    __slots__ = ("_pool", "_clock")

    def __init__(self, pool: asyncpg.Pool, *, clock: Callable[[], datetime] = utcnow) -> None:
        self._pool = pool
        self._clock = clock

    def __repr__(self) -> str:
        return "PostgresExecutionLedger(bounded=False)"

    async def commit(self, write: AtomicLedgerWrite) -> LedgerMutationOutcome:
        if type(write) is not AtomicLedgerWrite:
            raise TypeError("write must be an exact AtomicLedgerWrite")
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await lock_scope(conn, write.command.scope)
                replay = await self._replay_outcome(conn, write)
                if replay is not None:
                    return replay
                now = _aware("ledger clock", self._clock())
                state = await hydrate(conn, write.command.scope)
                decision = validate_write(state, write, now=now)
                append = AtomicEventAppend(write.event, write.outbox)
                status = decision.status or event_preflight(state, append)
                if status is not None:
                    outcome = _outcome(write, status, decision.previous_version, None)
                    await insert_command(conn, write, outcome, now=now)
                    return outcome
                recorded, outbox = materialize_event(state, append, now=now)
                resulting = decision.previous_version + 1
                outcome = _outcome(
                    write, LedgerMutationStatus.APPLIED, decision.previous_version, resulting
                )
                await upsert_record(conn, write.record)
                await insert_event(conn, recorded)
                await insert_outbox(conn, outbox, write.outbox)
                await insert_command(conn, write, outcome, now=now)
                return outcome

    async def _replay_outcome(
        self, conn: asyncpg.Connection, write: AtomicLedgerWrite
    ) -> LedgerMutationOutcome | None:
        """Mirror ``MemoryExecutionLedger._replay_outcome`` over the command row."""

        stored_outcome = await fetch_command_outcome(conn, write.command.scope, write.command.id)
        if stored_outcome is None:
            return None
        submitted = await fetch_stored_write(conn, write.command.scope, write.command.id)
        decision = classify_command_replay(write.command, submitted.command)
        if decision is CommandReplayDecision.REPLAY and submitted == write:
            return replace(stored_outcome, status=LedgerMutationStatus.REPLAYED)
        return _outcome(write, LedgerMutationStatus.CONFLICT, None, None)

    async def append_event(self, append: AtomicEventAppend) -> EventAppendOutcome:
        if type(append) is not AtomicEventAppend:
            raise TypeError("append must be an exact AtomicEventAppend")
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await lock_scope(conn, append.event.scope)
                now = _aware("ledger clock", self._clock())
                state = await hydrate(conn, append.event.scope)
                outcome = append_event_locked(state, _UNBOUNDED, append, now=now)
                if outcome.status is not AppendStatus.INSERTED or outcome.event is None:
                    return outcome
                await insert_event(conn, outcome.event)
                await insert_outbox(conn, outcome.outbox, append.outbox)
                return outcome

    async def write_runtime_identity(
        self, identity: RuntimeIdentity, *, expected_generation: int
    ) -> RuntimeIdentityWriteOutcome:
        if type(identity) is not RuntimeIdentity:
            raise TypeError("identity must be an exact RuntimeIdentity")
        _nonnegative("expected_generation", expected_generation)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await lock_workspace_exclusive(conn, identity.workspace)
                now = _aware("ledger clock", self._clock())
                state = await hydrate_identities(
                    conn, identity.workspace, MemoryLedgerState()
                )
                outcome = write_runtime_identity_locked(
                    state,
                    _UNBOUNDED,
                    identity,
                    expected_generation=expected_generation,
                    now=now,
                )
                if outcome.status is AppendStatus.INSERTED and outcome.identity is not None:
                    await upsert_identity(conn, outcome.identity, now=now)
                return outcome

    async def append_binding(self, binding: CodexBinding) -> BindingWriteOutcome:
        if type(binding) not in {CodexThreadBinding, CodexTurnBinding, CodexItemBinding}:
            raise TypeError("binding must be an exact Codex binding")
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await lock_scope(conn, binding.scope)
                now = _aware("ledger clock", self._clock())
                state = await hydrate(conn, binding.scope)
                outcome = append_binding_locked(state, _UNBOUNDED, binding, now=now)
                if outcome.status is AppendStatus.INSERTED and outcome.binding is not None:
                    await insert_binding(conn, outcome.binding)
                return outcome

    async def get_root(self, scope: ExecutionScopeRef) -> ExecutionRootRun | None:
        _scope(scope)
        async with self._pool.acquire() as conn:
            return cast(ExecutionRootRun | None, await fetch_root(conn, scope))

    async def get_phase(self, scope: ExecutionScopeRef, phase_id: str) -> ExecutionPhase | None:
        return cast(
            ExecutionPhase | None,
            await self._get(scope, phase_id, ExecutionAggregateKind.PHASE),
        )

    async def get_work_item(
        self, scope: ExecutionScopeRef, work_item_id: str
    ) -> ExecutionWorkItem | None:
        return cast(
            ExecutionWorkItem | None,
            await self._get(scope, work_item_id, ExecutionAggregateKind.WORK_ITEM),
        )

    async def get_assignment(
        self, scope: ExecutionScopeRef, assignment_id: str
    ) -> ExecutionAssignment | None:
        return cast(
            ExecutionAssignment | None,
            await self._get(scope, assignment_id, ExecutionAggregateKind.ASSIGNMENT),
        )

    async def get_result(
        self, scope: ExecutionScopeRef, result_id: str
    ) -> ExecutionResult | None:
        return cast(
            ExecutionResult | None,
            await self._get(scope, result_id, ExecutionAggregateKind.RESULT),
        )

    async def get_verification(
        self, scope: ExecutionScopeRef, verification_id: str
    ) -> ExecutionVerification | None:
        return cast(
            ExecutionVerification | None,
            await self._get(scope, verification_id, ExecutionAggregateKind.VERIFICATION),
        )

    async def _get(
        self, scope: ExecutionScopeRef, item_id: str, kind: ExecutionAggregateKind
    ) -> Any:
        _scope(scope)
        _identifier("aggregate_id", item_id)
        async with self._pool.acquire() as conn:
            return await fetch_aggregate(conn, scope, item_id, kind)

    async def get_command_outcome(
        self, scope: ExecutionScopeRef, command_id: str
    ) -> LedgerMutationOutcome | None:
        _scope(scope)
        _identifier("command_id", command_id)
        async with self._pool.acquire() as conn:
            return await fetch_command_outcome(conn, scope, command_id)

    async def get_runtime_identity(
        self, workspace: WorkspaceScopeRef, identity_id: str
    ) -> RuntimeIdentity | None:
        if type(workspace) is not WorkspaceScopeRef:
            raise TypeError("workspace must be an exact WorkspaceScopeRef")
        _identifier("identity_id", identity_id)
        async with self._pool.acquire() as conn:
            return await fetch_identity(conn, workspace, identity_id)

    async def list_events(
        self, scope: ExecutionScopeRef, *, after_sequence: int = 0, limit: int = 100
    ) -> tuple[RecordedExecutionEvent, ...]:
        _scope(scope)
        _page(after_sequence, limit)
        async with self._pool.acquire() as conn:
            return await fetch_events(conn, scope, after_sequence=after_sequence, limit=limit)

    async def list_outbox(
        self, scope: ExecutionScopeRef, *, limit: int = 100
    ) -> tuple[ExecutionOutboxRecord, ...]:
        _scope(scope)
        _page(0, limit)
        async with self._pool.acquire() as conn:
            return await fetch_outbox(conn, scope, limit=limit)


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


__all__ = ["PostgresExecutionLedger"]
