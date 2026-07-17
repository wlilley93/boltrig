"""PostgresExecutionLedger: the shared contract holds on real PostgreSQL.

Runs only when BOLTRIG_TEST_DATABASE_URL points at a Postgres (CI provides a
service; offline the class skips cleanly, P9). Proves the durable adapter
satisfies the same atomic commit / replay / conflict / hierarchy / cancellation /
runtime-ownership semantics as the in-memory adapter, including the concurrent
compare-and-swap race, via the same seven store-agnostic asserts the memory
adapter is held to.

The pool/DDL fixtures live in ``tests.store.execution_ledger_pg`` and are shared
with ``test_postgres_execution_ledger_proofs``, which carries the lock-order,
command-to-row, and revocation-race proofs.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from boltrig.fleet.infrastructure.memory_execution_ledger import MemoryExecutionLedger
from boltrig.fleet.infrastructure.postgres_execution_ledger import PostgresExecutionLedger
from boltrig.fleet.ports.execution_ledger import (
    AtomicEventAppend,
    ExecutionLedgerStore,
    OutboxIntent,
)
from boltrig.models import LedgerCommandKind

from tests.store.execution_ledger_pg import pg_only
from tests.unit.execution_ledger_cancellation_contract import (
    assert_cancellation_retry_and_terminal_ordering,
)
from tests.unit.execution_ledger_contract import (
    assert_atomic_replay_conflict_and_scope,
    assert_concurrent_compare_and_swap_is_atomic,
    assert_normalized_events_are_exact_and_monotonic,
)
from tests.unit.execution_ledger_fixtures import CLOCK_NOW, NOW, LedgerValues
from tests.unit.execution_ledger_lifecycle_contract import (
    assert_assignment_attestation_set_round_trips,
    assert_assignment_authority_matches_phase_policy,
    assert_hierarchy_lifecycle_and_atomic_outbox,
    assert_runtime_identity_and_binding_ownership,
)


@pg_only
async def test_postgres_store_atomic_replay_conflict_and_scope(
    ledger: PostgresExecutionLedger,
) -> None:
    await assert_atomic_replay_conflict_and_scope(ledger)


@pg_only
async def test_postgres_store_compare_and_swap_is_concurrency_safe(
    ledger: PostgresExecutionLedger,
) -> None:
    await assert_concurrent_compare_and_swap_is_atomic(ledger)


@pg_only
async def test_postgres_store_event_stream_is_exact_and_monotonic(
    ledger: PostgresExecutionLedger,
) -> None:
    await assert_normalized_events_are_exact_and_monotonic(ledger)


@pg_only
async def test_postgres_store_enforces_hierarchy_lifecycle_and_atomic_outbox(
    ledger: PostgresExecutionLedger,
) -> None:
    await assert_hierarchy_lifecycle_and_atomic_outbox(ledger)


@pg_only
async def test_postgres_store_binds_assignment_authority_to_phase_policy(
    ledger: PostgresExecutionLedger,
) -> None:
    await assert_assignment_authority_matches_phase_policy(ledger)


@pg_only
async def test_postgres_store_round_trips_assignment_attestation_set(
    ledger: PostgresExecutionLedger,
) -> None:
    await assert_assignment_attestation_set_round_trips(ledger)


@pg_only
async def test_postgres_store_runtime_identity_and_binding_ownership(
    ledger: PostgresExecutionLedger,
) -> None:
    await assert_runtime_identity_and_binding_ownership(ledger)


@pg_only
async def test_postgres_store_cancellation_retry_and_terminal_ordering(
    ledger: PostgresExecutionLedger,
) -> None:
    await assert_cancellation_retry_and_terminal_ordering(ledger)


async def _replay_statuses(store: ExecutionLedgerStore) -> list[str]:
    """Drive one append plus three near-identical resubmissions through a store.

    Each resubmission differs from the original in exactly one way the durable
    schema used to erase, so the returned statuses pin the store's replay
    comparison to the byte the caller actually submitted.
    """

    values = LedgerValues()
    root = values.root()
    await store.commit(
        values.write(
            root, LedgerCommandKind.CREATE_ROOT, expected_version=0, command_id="create-root"
        )
    )
    base = values.runtime_event(root, identifier="runtime-10", source_sequence=10)
    first = OutboxIntent("outbox-first", "execution.timeline", "deliver-first", NOW)
    second = OutboxIntent("outbox-second", "execution.timeline", "deliver-second", NOW)
    statuses = [(await store.append_event(AtomicEventAppend(base.event, (second, first)))).status]

    # Identical resubmission: replayed.
    statuses.append(
        (await store.append_event(AtomicEventAppend(base.event, (second, first)))).status
    )
    # Only available_at differs, and it clamps to the same materialized value
    # (both NOW and NOW+10s are below the CLOCK_NOW the store materialises at),
    # so a store that kept only the materialized value cannot tell these apart.
    nudged = replace(second, available_at=NOW + timedelta(seconds=10))
    statuses.append(
        (await store.append_event(AtomicEventAppend(base.event, (nudged, first)))).status
    )
    # Same intents, submitted in the other order: the tuple is order-sensitive.
    statuses.append(
        (await store.append_event(AtomicEventAppend(base.event, (first, second)))).status
    )
    return [item.value for item in statuses]


@pg_only
async def test_postgres_store_replay_comparison_is_exact_and_matches_memory(
    ledger: PostgresExecutionLedger,
) -> None:
    """The durable store conflicts exactly where the memory store conflicts.

    Both differences below survive only because ``execution_outbox`` now keeps the
    requested ``available_at`` and the submitted ``intent_ordinal`` (0031). Without
    those columns the store had to infer the submitted intent from the materialized
    row and would answer "replayed" to both, silently accepting an append that was
    not the one it had already recorded.
    """

    durable = await _replay_statuses(ledger)
    memory = await _replay_statuses(MemoryExecutionLedger(clock=lambda: CLOCK_NOW))

    assert durable == ["inserted", "replayed", "conflict", "conflict"]
    assert durable == memory
