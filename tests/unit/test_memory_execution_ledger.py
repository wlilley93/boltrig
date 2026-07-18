from __future__ import annotations

import pytest

from boltrig.fleet.infrastructure.memory_execution_ledger import (
    MemoryExecutionLedger,
    MemoryLedgerLimits,
)
from boltrig.fleet.ports.execution_ledger import AppendStatus
from boltrig.models import (
    CodexBindingKind,
    CodexTurnBinding,
    LedgerCommandKind,
    LedgerMutationStatus,
)

from .execution_ledger_cancellation_contract import (
    assert_cancellation_retry_and_terminal_ordering,
)
from .execution_ledger_contract import (
    assert_atomic_replay_conflict_and_scope,
    assert_concurrent_compare_and_swap_is_atomic,
    assert_normalized_events_are_exact_and_monotonic,
)
from .execution_ledger_fixtures import CLOCK_NOW, LedgerValues
from .execution_ledger_lifecycle_contract import (
    assert_assignment_attestation_set_round_trips,
    assert_assignment_authority_matches_phase_policy,
    assert_hierarchy_lifecycle_and_atomic_outbox,
    assert_runtime_identity_and_binding_ownership,
    seed_running_work,
)


def _store(*, limits: MemoryLedgerLimits | None = None) -> MemoryExecutionLedger:
    return MemoryExecutionLedger(clock=lambda: CLOCK_NOW, limits=limits)


@pytest.mark.asyncio
async def test_memory_store_atomic_replay_conflict_and_scope() -> None:
    await assert_atomic_replay_conflict_and_scope(_store())


@pytest.mark.asyncio
async def test_memory_store_compare_and_swap_is_concurrency_safe() -> None:
    await assert_concurrent_compare_and_swap_is_atomic(_store())


@pytest.mark.asyncio
async def test_memory_store_event_stream_is_exact_and_monotonic() -> None:
    await assert_normalized_events_are_exact_and_monotonic(_store())


@pytest.mark.asyncio
async def test_memory_store_enforces_hierarchy_lifecycle_and_atomic_outbox() -> None:
    await assert_hierarchy_lifecycle_and_atomic_outbox(_store())


@pytest.mark.asyncio
async def test_memory_store_binds_assignment_authority_to_phase_policy() -> None:
    await assert_assignment_authority_matches_phase_policy(_store())


@pytest.mark.asyncio
async def test_memory_store_round_trips_assignment_attestation_set() -> None:
    await assert_assignment_attestation_set_round_trips(_store())


@pytest.mark.asyncio
async def test_memory_store_runtime_identity_and_binding_ownership() -> None:
    await assert_runtime_identity_and_binding_ownership(_store())


@pytest.mark.asyncio
async def test_memory_store_cancellation_retry_and_terminal_ordering() -> None:
    await assert_cancellation_retry_and_terminal_ordering(_store())


@pytest.mark.asyncio
async def test_memory_store_fails_closed_at_hard_capacity() -> None:
    limits = MemoryLedgerLimits(
        roots=1,
        records=1,
        commands=8,
        events=1,
        outbox=1,
        identities=1,
        bindings=1,
    )
    store = _store(limits=limits)
    first = LedgerValues()
    second = LedgerValues("org-b", "workspace-b", "run-b")
    create = first.write(
        first.root(),
        LedgerCommandKind.CREATE_ROOT,
        expected_version=0,
        command_id="create-first",
    )
    assert (await store.commit(create)).status is LedgerMutationStatus.APPLIED
    denied = await store.commit(
        second.write(
            second.root(),
            LedgerCommandKind.CREATE_ROOT,
            expected_version=0,
            command_id="create-second",
        )
    )
    assert denied.status is LedgerMutationStatus.REJECTED
    assert await store.get_root(second.scope) is None
    assert len(await store.list_events(first.scope)) == 1
    assert len(await store.list_outbox(first.scope)) == 1

    identity_store = _store(
        limits=MemoryLedgerLimits(
            roots=1,
            records=1,
            commands=1,
            events=1,
            outbox=1,
            identities=1,
            bindings=1,
        )
    )
    assert (
        await identity_store.write_runtime_identity(first.identity(), expected_generation=0)
    ).status is AppendStatus.INSERTED
    assert (
        await identity_store.write_runtime_identity(second.identity(), expected_generation=0)
    ).status is AppendStatus.REJECTED

    binding_store = _store(
        limits=MemoryLedgerLimits(
            roots=2,
            records=16,
            commands=32,
            events=32,
            outbox=32,
            identities=2,
            bindings=1,
        )
    )
    await seed_running_work(binding_store, first)
    assert (await binding_store.append_binding(first.thread())).status is AppendStatus.INSERTED
    turn = CodexTurnBinding(
        first.scope,
        first.thread(),
        CodexBindingKind.PHASE,
        "turn-over-limit",
        bound_at=CLOCK_NOW,
    )
    assert (await binding_store.append_binding(turn)).status is AppendStatus.REJECTED
