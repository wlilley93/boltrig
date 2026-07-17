"""The three proofs slice 3 left open for the durable execution ledger.

1. ``test_interleaved_lock_takers_never_deadlock`` - real contention over both
   advisory locks, from many connections at once.
2. ``test_every_command_kind_writes_exactly_its_rows`` - the exact command-to-row
   transition for all nine ``LedgerCommandKind`` values, asserted at the SQL level
   rather than through the adapter's own reads (which would be circular).
3. ``test_in_flight_commit_holds_off_identity_revocation`` plus
   ``test_identity_revocation_racing_a_commit_is_coherent`` - identity revocation
   racing a commit that validates against that identity.

On the deadlock claim, honestly. ``lock_scope`` takes the workspace lock SHARED
and then the scope lock EXCLUSIVE; ``lock_workspace_exclusive`` takes the
workspace lock EXCLUSIVE and nothing else. No caller takes the scope lock before
the workspace lock, and no caller upgrades a shared workspace lock to exclusive
(the two entry points are disjoint: ``write_runtime_identity`` never calls
``lock_scope``). Every transaction therefore acquires at most one lock at each of
two levels, always workspace-then-scope, so the wait-for graph is acyclic by the
classic resource-ordering argument and NO lock-order cycle is reachable by
construction. The only theoretical cycle needs a ``hashtext`` collision between a
workspace key and a scope key, which would collapse the two levels onto one lock
and turn ``lock_scope`` into a shared-to-exclusive self-upgrade; a 32-bit
collision is not reachable in a test and is not what this proves. Test 1 is
therefore a REGRESSION GUARD over that ordering, not a discovery of a cycle: it
fails loudly if a future change introduces one. It is mutation-proven against an
injected shared-to-exclusive upgrade, which is the classic way to break this.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any

import asyncpg

from boltrig.fleet.infrastructure.memory_ledger_state import scope_key, workspace_key
from boltrig.fleet.infrastructure.postgres_execution_ledger import PostgresExecutionLedger
from boltrig.fleet.ports.execution_ledger import AppendStatus, AtomicLedgerWrite
from boltrig.models import (
    AssignmentStatus,
    CancellationMetadata,
    ExecutionAggregateKind,
    ExecutionPhaseStatus,
    ExecutionScopeRef,
    LedgerCommandKind,
    LedgerMutationOutcome,
    LedgerMutationStatus,
    LedgerWorkItemStatus,
    RootRunStatus,
    RuntimeIdentity,
    RuntimeIdentityStatus,
)

from tests.store.execution_ledger_pg import pg_only
from tests.unit.execution_ledger_fixtures import CLOCK_NOW, LedgerValues, digest
from tests.unit.execution_ledger_lifecycle_contract import seed_running_work

_SCOPE_WHERE = "tenant_id = $1 AND workspace_id = $2 AND root_run_id = $3"

_RECORD_TABLES = (
    "execution_root_runs",
    "execution_phases",
    "execution_work_items",
    "execution_assignments",
    "execution_results",
    "execution_verifications",
)
_LEDGER_TABLES = _RECORD_TABLES + (
    "execution_commands",
    "execution_events",
    "execution_outbox",
)
_RECORD_TABLE_BY_KIND: dict[ExecutionAggregateKind, str] = {
    ExecutionAggregateKind.ROOT_RUN: "execution_root_runs",
    ExecutionAggregateKind.PHASE: "execution_phases",
    ExecutionAggregateKind.WORK_ITEM: "execution_work_items",
    ExecutionAggregateKind.ASSIGNMENT: "execution_assignments",
    ExecutionAggregateKind.RESULT: "execution_results",
    ExecutionAggregateKind.VERIFICATION: "execution_verifications",
}

# execution_results and execution_verifications carry no version column: neither
# model has a version field, so their compare-and-swap version lives only in the
# applied command's resulting_version (the accepted deviation this adapter
# landed with). The probe asserts the command row for those two kinds and the
# record row's presence, and the version column for the other four.
Snapshot = dict[str, list[dict[str, Any]]]


async def _snapshot(conn: asyncpg.Connection, scope: ExecutionScopeRef) -> Snapshot:
    """Every durable row of one scope, read straight from SQL."""

    snapshot: Snapshot = {}
    for table in _LEDGER_TABLES:
        rows = await conn.fetch(
            f"SELECT * FROM {table} WHERE {_SCOPE_WHERE}", *scope_key(scope)
        )
        snapshot[table] = [dict(row) for row in rows]
    return snapshot


def _added(before: Snapshot, after: Snapshot, table: str) -> list[dict[str, Any]]:
    """Rows present after but not before, by exact value (an upsert reads as new)."""

    old = {repr(row) for row in before[table]}
    return [row for row in after[table] if repr(row) not in old]


def _same(before: Snapshot, after: Snapshot, table: str) -> bool:
    return {repr(row) for row in before[table]} == {repr(row) for row in after[table]}


def _row_id(row: dict[str, Any], kind: ExecutionAggregateKind) -> str:
    identifier = row["root_run_id"] if kind is ExecutionAggregateKind.ROOT_RUN else row["id"]
    return str(identifier)


@dataclass(frozen=True)
class _Probe:
    """Commit through the adapter, then assert the row delta directly in SQL."""

    conn: asyncpg.Connection
    store: PostgresExecutionLedger
    scope: ExecutionScopeRef

    async def applied(
        self, write: AtomicLedgerWrite, *, previous: int, resulting: int
    ) -> None:
        before = await _snapshot(self.conn, self.scope)
        outcome = await self.store.commit(write)
        after = await _snapshot(self.conn, self.scope)

        assert outcome.status is LedgerMutationStatus.APPLIED
        assert (outcome.previous_version, outcome.resulting_version) == (previous, resulting)
        self._assert_command(before, after, write, LedgerMutationStatus.APPLIED, previous)
        command = _added(before, after, "execution_commands")[0]
        assert command["resulting_version"] == resulting

        sequence = self._assert_event(before, after, write)
        self._assert_outbox(before, after, write, sequence)
        self._assert_record(before, after, write, resulting)

    async def terminal(
        self, write: AtomicLedgerWrite, *, status: LedgerMutationStatus, previous: int
    ) -> None:
        """A terminal outcome writes the command row and nothing else, ever."""

        assert status in {
            LedgerMutationStatus.CONFLICT,
            LedgerMutationStatus.REJECTED,
            LedgerMutationStatus.NOT_FOUND,
        }
        before = await _snapshot(self.conn, self.scope)
        outcome = await self.store.commit(write)
        after = await _snapshot(self.conn, self.scope)

        assert outcome.status is status
        assert outcome.previous_version == previous
        assert outcome.resulting_version is None
        self._assert_command(before, after, write, status, previous)
        command = _added(before, after, "execution_commands")[0]
        assert command["resulting_version"] is None

        for table in _LEDGER_TABLES:
            if table == "execution_commands":
                continue
            assert _same(before, after, table), (
                f"a {status.value} command wrote to {table}: a terminal outcome must "
                "write only its command row"
            )

    async def replayed(self, write: AtomicLedgerWrite) -> None:
        before = await _snapshot(self.conn, self.scope)
        outcome = await self.store.commit(write)
        after = await _snapshot(self.conn, self.scope)

        assert outcome.status is LedgerMutationStatus.REPLAYED
        for table in _LEDGER_TABLES:
            assert _same(before, after, table), f"a replayed command wrote to {table}"

    def _assert_command(
        self,
        before: Snapshot,
        after: Snapshot,
        write: AtomicLedgerWrite,
        status: LedgerMutationStatus,
        previous: int,
    ) -> None:
        commands = _added(before, after, "execution_commands")
        assert len(commands) == 1, f"expected exactly one new command row, got {len(commands)}"
        command = commands[0]
        assert command["command_id"] == write.command.id
        assert command["request_digest"] == write.command.request_digest
        assert command["aggregate_kind"] == write.command.aggregate_kind.value
        assert command["aggregate_id"] == write.command.aggregate_id
        assert command["status"] == status.value
        assert command["previous_version"] == previous
        # The ledger's time is the caller's injected clock, never Postgres now().
        assert command["recorded_at"] == CLOCK_NOW

    def _assert_event(
        self, before: Snapshot, after: Snapshot, write: AtomicLedgerWrite
    ) -> int:
        events = _added(before, after, "execution_events")
        assert len(events) == 1, f"expected exactly one new event row, got {len(events)}"
        event = events[0]
        assert event["event_id"] == write.event.id
        assert event["causation_command_id"] == write.command.id
        assert event["kind"] == write.event.kind.value
        assert event["aggregate_kind"] == write.command.aggregate_kind.value
        assert event["aggregate_id"] == write.command.aggregate_id
        assert event["idempotency_key"] == write.event.ingestion_idempotency_key

        highest = max(
            (row["sequence"] for row in before["execution_events"]), default=0
        )
        assert event["sequence"] == highest + 1
        sequences = sorted(row["sequence"] for row in after["execution_events"])
        assert sequences == list(range(1, len(sequences) + 1))
        return int(event["sequence"])

    def _assert_outbox(
        self, before: Snapshot, after: Snapshot, write: AtomicLedgerWrite, sequence: int
    ) -> None:
        outbox = _added(before, after, "execution_outbox")
        assert len(outbox) == len(write.outbox)
        assert {row["id"] for row in outbox} == {intent.id for intent in write.outbox}
        assert all(row["event_sequence"] == sequence for row in outbox)
        assert sorted(row["intent_ordinal"] for row in outbox) == list(
            range(len(write.outbox))
        )

    def _assert_record(
        self, before: Snapshot, after: Snapshot, write: AtomicLedgerWrite, resulting: int
    ) -> None:
        kind = write.command.aggregate_kind
        table = _RECORD_TABLE_BY_KIND[kind]
        records = _added(before, after, table)
        assert len(records) == 1, f"expected exactly one new/updated {table} row"
        assert _row_id(records[0], kind) == write.command.aggregate_id
        if "version" in records[0]:
            assert records[0]["version"] == resulting
        for other in _RECORD_TABLES:
            if other != table:
                assert _same(before, after, other), (
                    f"a {kind.value} command mutated {other}"
                )


def _revoked(values: LedgerValues) -> RuntimeIdentity:
    identity = values.identity()
    return RuntimeIdentity(
        identity.id,
        identity.principal,
        identity.workspace,
        2,
        RuntimeIdentityStatus.REVOKED,
        identity.created_at,
        CLOCK_NOW,
    )


async def _advisory_ids(conn: asyncpg.Connection, key: str) -> tuple[int, int]:
    """The (classid, objid) pg_locks reports for pg_advisory_xact_lock(hashtext(key)).

    hashtext returns int4, which widens to the bigint overload, and the lock tag
    splits that bigint into its high and low 32-bit halves.
    """

    value = await conn.fetchval("SELECT hashtext($1)::bigint", key)
    return ((value >> 32) & 0xFFFFFFFF, value & 0xFFFFFFFF)


async def _is_waiting(pool: asyncpg.Pool, ids: tuple[int, int]) -> bool:
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
            "AND classid::bigint = $1 AND objid::bigint = $2 AND NOT granted",
            *ids,
        )
    return bool(count)


async def _until(
    predicate: Callable[[], Awaitable[bool]], *, timeout: float = 15.0
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await predicate():
            return True
        await asyncio.sleep(0.02)
    return False


@pg_only
async def test_every_command_kind_writes_exactly_its_rows(
    ledger_pool: asyncpg.Pool, ledger: PostgresExecutionLedger
) -> None:
    """Each of the nine command kinds writes exactly the rows it should.

    Asserted straight against execution_commands / execution_events /
    execution_outbox and the six record tables, never through the adapter's own
    reads, so a read that agrees with a broken write cannot hide the break. Every
    kind is driven applied (exactly one command row, one event row at the next
    sequence, its outbox rows, and the aggregate at the resulting version),
    replayed (nothing new anywhere), and terminal (only the command row).
    """

    values = LedgerValues(run="run-transitions")
    async with ledger_pool.acquire() as conn:
        probe = _Probe(conn, ledger, values.scope)

        # 1. create_root
        root = values.root()
        create_root = values.write(
            root, LedgerCommandKind.CREATE_ROOT, expected_version=0, command_id="create-root"
        )
        await probe.applied(create_root, previous=0, resulting=1)
        await probe.replayed(create_root)
        await probe.terminal(
            values.write(
                root,
                LedgerCommandKind.CREATE_ROOT,
                expected_version=1,
                command_id="recreate-root",
            ),
            status=LedgerMutationStatus.CONFLICT,
            previous=1,
        )

        # 2. transition_status (applied here, terminal once work exists)
        running_root = replace(root, status=RootRunStatus.RUNNING, version=2)
        start_root = values.write(
            running_root,
            LedgerCommandKind.TRANSITION_STATUS,
            expected_version=1,
            command_id="start-root",
        )
        await probe.applied(start_root, previous=1, resulting=2)
        await probe.replayed(start_root)

        # 3. create_phase
        phase = values.phase()
        create_phase = values.write(
            phase, LedgerCommandKind.CREATE_PHASE, expected_version=0, command_id="create-phase"
        )
        await probe.applied(create_phase, previous=0, resulting=1)
        await probe.replayed(create_phase)
        orphan = LedgerValues(run="run-orphan")
        await _Probe(conn, ledger, orphan.scope).terminal(
            orphan.write(
                orphan.phase(),
                LedgerCommandKind.CREATE_PHASE,
                expected_version=0,
                command_id="orphan-phase",
            ),
            status=LedgerMutationStatus.NOT_FOUND,
            previous=0,
        )

        starting = replace(phase, status=ExecutionPhaseStatus.STARTING, version=2)
        await probe.applied(
            values.write(
                starting,
                LedgerCommandKind.TRANSITION_STATUS,
                expected_version=1,
                command_id="start-phase",
            ),
            previous=1,
            resulting=2,
        )
        await probe.applied(
            values.write(
                replace(starting, status=ExecutionPhaseStatus.RUNNING, version=3),
                LedgerCommandKind.TRANSITION_STATUS,
                expected_version=2,
                command_id="run-phase",
            ),
            previous=2,
            resulting=3,
        )

        # 4. enqueue_work
        work = values.work()
        enqueue_work = values.write(
            work, LedgerCommandKind.ENQUEUE_WORK, expected_version=0, command_id="create-work"
        )
        await probe.applied(enqueue_work, previous=0, resulting=1)
        await probe.replayed(enqueue_work)
        await probe.terminal(
            values.write(
                replace(work, id="work-b", ordinal=2, version=2),
                LedgerCommandKind.ENQUEUE_WORK,
                expected_version=0,
                command_id="reject-work-version",
            ),
            status=LedgerMutationStatus.REJECTED,
            previous=0,
        )
        in_flight = replace(work, status=LedgerWorkItemStatus.IN_FLIGHT, version=2)
        await probe.applied(
            values.write(
                in_flight,
                LedgerCommandKind.TRANSITION_STATUS,
                expected_version=1,
                command_id="start-work",
            ),
            previous=1,
            resulting=2,
        )
        await probe.terminal(
            values.write(
                replace(work, status=LedgerWorkItemStatus.DONE, version=3),
                LedgerCommandKind.TRANSITION_STATUS,
                expected_version=2,
                command_id="premature-done",
            ),
            status=LedgerMutationStatus.REJECTED,
            previous=2,
        )

        identity = await ledger.write_runtime_identity(values.identity(), expected_generation=0)
        assert identity.status is AppendStatus.INSERTED

        # 5. assign_work
        assignment = values.assignment()
        assign_work = values.write(
            assignment, LedgerCommandKind.ASSIGN_WORK, expected_version=0, command_id="assign-work"
        )
        await probe.applied(assign_work, previous=0, resulting=1)
        await probe.replayed(assign_work)
        await probe.terminal(
            values.write(
                replace(values.assignment(authority_policy_generation=4), id="assignment-stale"),
                LedgerCommandKind.ASSIGN_WORK,
                expected_version=0,
                command_id="reject-stale-authority",
            ),
            status=LedgerMutationStatus.REJECTED,
            previous=0,
        )
        claimed = replace(
            assignment, status=AssignmentStatus.CLAIMED, lease=values.lease(), version=2
        )
        await probe.applied(
            values.write(
                claimed,
                LedgerCommandKind.TRANSITION_STATUS,
                expected_version=1,
                command_id="claim-work",
            ),
            previous=1,
            resulting=2,
        )
        await probe.applied(
            values.write(
                replace(claimed, status=AssignmentStatus.RUNNING, version=3),
                LedgerCommandKind.TRANSITION_STATUS,
                expected_version=2,
                command_id="run-work",
            ),
            previous=2,
            resulting=3,
        )

        # 6. record_result
        record_result = values.write(
            values.result(),
            LedgerCommandKind.RECORD_RESULT,
            expected_version=0,
            command_id="record-result",
        )
        await probe.applied(record_result, previous=0, resulting=1)
        await probe.replayed(record_result)
        await probe.terminal(
            values.write(
                values.result(assignment_id="assignment-missing"),
                LedgerCommandKind.RECORD_RESULT,
                expected_version=0,
                command_id="result-without-assignment",
            ),
            status=LedgerMutationStatus.NOT_FOUND,
            previous=0,
        )

        # 7. record_verification
        record_verification = values.write(
            values.verification(),
            LedgerCommandKind.RECORD_VERIFICATION,
            expected_version=0,
            command_id="record-verification",
        )
        await probe.applied(record_verification, previous=0, resulting=1)
        await probe.replayed(record_verification)
        await probe.terminal(
            values.write(
                replace(values.verification(result_id="result-missing"), id="verification-missing"),
                LedgerCommandKind.RECORD_VERIFICATION,
                expected_version=0,
                command_id="verification-without-result",
            ),
            status=LedgerMutationStatus.NOT_FOUND,
            previous=0,
        )

        # 8. replace_assignment
        await probe.terminal(
            values.write(
                replace(work, status=LedgerWorkItemStatus.CANCELLED, version=3),
                LedgerCommandKind.CANCEL,
                expected_version=2,
                command_id="premature-cancel-work",
            ),
            status=LedgerMutationStatus.REJECTED,
            previous=2,
        )
        await probe.applied(
            values.write(
                replace(claimed, status=AssignmentStatus.FAILED, version=4),
                LedgerCommandKind.TRANSITION_STATUS,
                expected_version=3,
                command_id="fail-first-attempt",
            ),
            previous=3,
            resulting=4,
        )
        replacement = values.assignment(attempt=2, replaces="assignment-1")
        replace_assignment = values.write(
            replacement,
            LedgerCommandKind.REPLACE_ASSIGNMENT,
            expected_version=0,
            command_id="replace-attempt",
        )
        await probe.applied(replace_assignment, previous=0, resulting=1)
        await probe.replayed(replace_assignment)
        await probe.terminal(
            values.write(
                replace(replacement, id="assignment-fork"),
                LedgerCommandKind.REPLACE_ASSIGNMENT,
                expected_version=0,
                command_id="fork-attempt",
            ),
            status=LedgerMutationStatus.CONFLICT,
            previous=0,
        )

        # 9. cancel
        cancel_root = values.write(
            replace(
                running_root,
                status=RootRunStatus.CANCELLING,
                cancellation=CancellationMetadata(
                    values.principal, "user.requested", CLOCK_NOW, digest("cancel-detail")
                ),
                version=3,
            ),
            LedgerCommandKind.CANCEL,
            expected_version=2,
            command_id="cancel-root",
        )
        await probe.applied(cancel_root, previous=2, resulting=3)
        await probe.replayed(cancel_root)

        kinds = await conn.fetch(
            "SELECT DISTINCT (submitted -> 'command' ->> 'kind') AS kind "
            f"FROM execution_commands WHERE {_SCOPE_WHERE}",
            *scope_key(values.scope),
        )
        assert {row["kind"] for row in kinds} == {
            kind.value for kind in LedgerCommandKind
        }, "the proof must drive every LedgerCommandKind"


@pg_only
async def test_interleaved_lock_takers_never_deadlock(
    ledger: PostgresExecutionLedger,
) -> None:
    """Every combination of lock takers, concurrently, from many connections.

    Commits on several scopes inside one workspace (workspace SHARED then scope
    EXCLUSIVE), runtime-identity writes on that same workspace (workspace
    EXCLUSIVE), plus event appends and binding appends, all racing on an 8
    connection pool. A Postgres deadlock surfaces as DeadlockDetectedError; this
    gathers without return_exceptions so one would fail the test loudly rather
    than be swallowed.

    Read the module docstring before trusting this: no lock-order cycle is
    reachable by construction, so this is a regression guard over the ordering,
    not a discovery. It is mutation-proven against a shared-to-exclusive upgrade
    injected into lock_scope, which does deadlock and which this catches.
    """

    scopes = [LedgerValues(run=f"run-lock-{index}") for index in range(6)]
    for values in scopes:
        await seed_running_work(ledger, values)

    # Every scope above shares one workspace, so the workspace-exclusive takers
    # added below contend with every scope-lock taker, not just one.
    assert len({values.scope.workspace for values in scopes}) == 1
    operations: list[Awaitable[object]] = []
    for values in scopes:
        run = values.run
        assignment = values.assignment()
        operations.append(
            ledger.commit(
                values.write(
                    values.result(),
                    LedgerCommandKind.RECORD_RESULT,
                    expected_version=0,
                    command_id=f"{run}-race-result",
                )
            )
        )
        operations.append(
            ledger.commit(
                values.write(
                    replace(assignment, status=AssignmentStatus.COMPLETED, version=4),
                    LedgerCommandKind.TRANSITION_STATUS,
                    expected_version=3,
                    command_id=f"{run}-race-complete",
                )
            )
        )
        operations.append(
            ledger.append_event(
                values.runtime_event(values.root(), identifier=f"{run}-rt-1", source_sequence=1)
            )
        )
        operations.append(
            ledger.append_event(
                values.runtime_event(values.root(), identifier=f"{run}-rt-2", source_sequence=2)
            )
        )
        operations.append(ledger.append_binding(values.thread(thread_id=f"{run}-thread")))

    # Workspace-exclusive takers, interleaved with the scope-lock takers above.
    for index in range(8):
        fresh = LedgerValues().identity(identity_id=f"runtime-lock-{index}")
        operations.append(ledger.write_runtime_identity(fresh, expected_generation=0))
        operations.append(
            ledger.write_runtime_identity(
                RuntimeIdentity(
                    fresh.id,
                    fresh.principal,
                    fresh.workspace,
                    2,
                    RuntimeIdentityStatus.REVOKED,
                    fresh.created_at,
                    CLOCK_NOW,
                ),
                expected_generation=1,
            )
        )

    assert len(operations) == 46
    results = await asyncio.gather(*operations)

    assert len(results) == len(operations)
    assert all(result is not None for result in results)


@pg_only
async def test_in_flight_commit_holds_off_identity_revocation(
    ledger_pool: asyncpg.Pool, ledger: PostgresExecutionLedger
) -> None:
    """A commit already inside lock_scope makes revocation wait for it.

    This is the proof the shared/exclusive workspace pairing was only reasoned
    about. The test parks a commit on the per-scope lock (which it can only reach
    AFTER taking the workspace lock shared), then starts a revocation of the very
    identity that commit validates against. With the pairing intact the
    revocation blocks on the workspace lock, the commit sees the ACTIVE identity
    and applies, and the revocation lands after it. Drop the shared workspace
    lock from lock_scope and the revocation sails through while the commit is
    still parked, the commit then hydrates a REVOKED identity, and it is
    REJECTED: two independent asserts below fail.
    """

    values = LedgerValues(run="run-revocation-order")
    await seed_running_work(ledger, values, include_assignment=False)
    revoked = _revoked(values)

    scope_lock = "\x1f".join(scope_key(values.scope))
    workspace_lock = "\x1f".join(workspace_key(values.scope.workspace))
    async with ledger_pool.acquire() as conn:
        scope_ids = await _advisory_ids(conn, scope_lock)
        workspace_ids = await _advisory_ids(conn, workspace_lock)

    async with ledger_pool.acquire() as blocker:
        transaction = blocker.transaction()
        await transaction.start()
        try:
            await blocker.execute("SELECT pg_advisory_xact_lock(hashtext($1))", scope_lock)
            commit = asyncio.create_task(
                ledger.commit(
                    values.write(
                        values.assignment(),
                        LedgerCommandKind.ASSIGN_WORK,
                        expected_version=0,
                        command_id="race-assign-work",
                    )
                )
            )
            parked = await _until(lambda: _is_waiting(ledger_pool, scope_ids))
            revoke = asyncio.create_task(
                ledger.write_runtime_identity(revoked, expected_generation=1)
            )

            async def _revocation_settled() -> bool:
                """The revocation has either blocked on the workspace lock or finished.

                Both branches must be awaited explicitly: `_is_waiting(...) or
                revoke.done()` would short-circuit on the truthy coroutine and
                never look at the task.
                """

                return revoke.done() or await _is_waiting(ledger_pool, workspace_ids)

            settled = await _until(_revocation_settled)
            held_off = not revoke.done()
        finally:
            await transaction.rollback()

    outcome = await commit
    revocation = await revoke

    assert parked, "the commit never parked on the per-scope advisory lock"
    assert settled, "the revocation neither blocked on nor acquired the workspace lock"
    assert held_off, (
        "the revocation acquired the workspace lock while a commit was mid-flight: "
        "lock_scope's shared workspace lock did not hold it back"
    )
    assert outcome.status is LedgerMutationStatus.APPLIED
    assert revocation.status is AppendStatus.INSERTED
    assert await ledger.get_assignment(values.scope, "assignment-1") == values.assignment()
    assert await ledger.get_runtime_identity(values.scope.workspace, "runtime-a") == revoked


@pg_only
async def test_identity_revocation_racing_a_commit_is_coherent(
    ledger_pool: asyncpg.Pool, ledger: PostgresExecutionLedger
) -> None:
    """Free-running races end in one of the two outcomes the pure helpers define.

    write_runtime_identity_locked accepts an ACTIVE -> REVOKED revision at the
    next generation unconditionally, and _validate_new_assignment REJECTS an
    assignment whose runtime identity is not ACTIVE. So each race must land on
    exactly one of: the commit validated the ACTIVE identity and APPLIED, or it
    saw the REVOKED identity and was REJECTED. Never torn - a REJECTED commit
    must leave no assignment row and no event, and an APPLIED one must leave
    exactly the rows an applied assignment writes.

    Weaker than the ordered test above by construction: once both transactions
    have committed, the identity is REVOKED either way, so the final rows cannot
    reveal which order the two ran in. What this pins is that no race produces a
    third outcome or a half-written one.
    """

    races = [LedgerValues(workspace=f"workspace-race-{index}") for index in range(8)]
    for values in races:
        await seed_running_work(ledger, values, include_assignment=False)

    async def _race(values: LedgerValues) -> tuple[LedgerMutationOutcome, AppendStatus]:
        commit = ledger.commit(
            values.write(
                values.assignment(),
                LedgerCommandKind.ASSIGN_WORK,
                expected_version=0,
                command_id="race-assign-work",
            )
        )
        revoke = ledger.write_runtime_identity(_revoked(values), expected_generation=1)
        outcome, revocation = await asyncio.gather(commit, revoke)
        return (outcome, revocation.status)

    outcomes = await asyncio.gather(*(_race(values) for values in races))

    async with ledger_pool.acquire() as conn:
        for values, (outcome, revocation) in zip(races, outcomes, strict=True):
            assert revocation is AppendStatus.INSERTED
            assert outcome.status in {
                LedgerMutationStatus.APPLIED,
                LedgerMutationStatus.REJECTED,
            }, f"revocation racing a commit produced {outcome.status.value}"
            assert (
                await ledger.get_runtime_identity(values.scope.workspace, "runtime-a")
                == _revoked(values)
            )

            snapshot = await _snapshot(conn, values.scope)
            assignments = snapshot["execution_assignments"]
            events = [
                row
                for row in snapshot["execution_events"]
                if row["causation_command_id"] == "race-assign-work"
            ]
            commands = [
                row
                for row in snapshot["execution_commands"]
                if row["command_id"] == "race-assign-work"
            ]
            assert len(commands) == 1
            assert commands[0]["status"] == outcome.status.value
            if outcome.status is LedgerMutationStatus.APPLIED:
                assert len(assignments) == 1
                assert assignments[0]["version"] == 1
                assert assignments[0]["runtime_identity_id"] == "runtime-a"
                assert len(events) == 1
            else:
                assert assignments == [], (
                    "a REJECTED commit left an assignment row: torn state"
                )
                assert events == [], "a REJECTED commit left an event row: torn state"


@pg_only
async def test_revocation_before_a_commit_rejects_the_assignment(
    ledger: PostgresExecutionLedger,
) -> None:
    """The other coherent outcome, pinned without a race: revoked first, rejected."""

    values = LedgerValues(run="run-revoked-first")
    await seed_running_work(ledger, values, include_assignment=False)
    revocation = await ledger.write_runtime_identity(_revoked(values), expected_generation=1)
    assert revocation.status is AppendStatus.INSERTED

    outcome = await ledger.commit(
        values.write(
            values.assignment(),
            LedgerCommandKind.ASSIGN_WORK,
            expected_version=0,
            command_id="assign-after-revocation",
        )
    )

    assert outcome.status is LedgerMutationStatus.REJECTED
    assert await ledger.get_assignment(values.scope, "assignment-1") is None
