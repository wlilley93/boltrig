"""Reusable atomicity, scoping, replay, and event-stream adapter contracts."""

from __future__ import annotations

import asyncio
from dataclasses import replace

from boltrig.fleet.ports.execution_ledger import (
    AppendStatus,
    AtomicEventAppend,
    AtomicLedgerWrite,
    ExecutionLedgerStore,
    OutboxIntent,
)
from boltrig.models import (
    CancellationMetadata,
    LedgerCommandKind,
    LedgerMutationStatus,
    RootRunStatus,
)

from .execution_ledger_fixtures import CLOCK_NOW, LedgerValues, NOW


async def assert_atomic_replay_conflict_and_scope(store: ExecutionLedgerStore) -> None:
    values = LedgerValues()
    root = values.root()
    write = values.write(
        root,
        LedgerCommandKind.CREATE_ROOT,
        expected_version=0,
        command_id="same-command-id",
    )

    inserted = await store.commit(write)
    replayed = await store.commit(write)
    changed_event = replace(
        write.event,
        id="event-tampered",
        ingestion_idempotency_key="ingest-tampered",
    )
    conflicted = await store.commit(
        AtomicLedgerWrite(write.command, root, changed_event, write.outbox)
    )

    assert inserted.status is LedgerMutationStatus.APPLIED
    assert replayed.status is LedgerMutationStatus.REPLAYED
    assert conflicted.status is LedgerMutationStatus.CONFLICT
    assert await store.get_root(values.scope) == root
    assert len(await store.list_events(values.scope)) == 1
    durable_outbox = await store.list_outbox(values.scope)
    assert len(durable_outbox) == 1
    assert durable_outbox[0].available_at == CLOCK_NOW

    other = LedgerValues("org-b", "workspace-b", "run-b")
    other_write = other.write(
        other.root(),
        LedgerCommandKind.CREATE_ROOT,
        expected_version=0,
        command_id="same-command-id",
    )
    assert (await store.commit(other_write)).status is LedgerMutationStatus.APPLIED
    assert await store.get_root(other.scope) == other.root()
    assert await store.get_root(
        LedgerValues("org-a", "workspace-a", "run-b").scope
    ) is None
    assert await store.get_command_outcome(other.scope, "same-command-id") is not None
    assert await store.get_command_outcome(
        LedgerValues("org-b", "workspace-b", "run-a").scope,
        "same-command-id",
    ) is None


async def assert_concurrent_compare_and_swap_is_atomic(store: ExecutionLedgerStore) -> None:
    values = LedgerValues()
    root = values.root()
    assert (
        await store.commit(
            values.write(
                root,
                LedgerCommandKind.CREATE_ROOT,
                expected_version=0,
                command_id="create-root",
            )
        )
    ).status is LedgerMutationStatus.APPLIED

    running = replace(root, status=RootRunStatus.RUNNING, version=2)
    cancellation = CancellationMetadata(
        values.principal, "user.requested", NOW, values.root().objective_digest
    )
    cancelled = replace(
        root,
        status=RootRunStatus.CANCELLED,
        cancellation=cancellation,
        version=2,
    )
    outcomes = await asyncio.gather(
        store.commit(
            values.write(
                running,
                LedgerCommandKind.TRANSITION_STATUS,
                expected_version=1,
                command_id="start-root",
            )
        ),
        store.commit(
            values.write(
                cancelled,
                LedgerCommandKind.CANCEL,
                expected_version=1,
                command_id="cancel-root",
            )
        ),
    )

    assert sorted(item.status.value for item in outcomes) == ["applied", "conflict"]
    stored = await store.get_root(values.scope)
    assert stored is not None and stored.version == 2
    assert len(await store.list_events(values.scope)) == 2
    assert len(await store.list_outbox(values.scope)) == 2


async def assert_normalized_events_are_exact_and_monotonic(
    store: ExecutionLedgerStore,
) -> None:
    values = LedgerValues()
    root = values.root()
    await store.commit(
        values.write(
            root,
            LedgerCommandKind.CREATE_ROOT,
            expected_version=0,
            command_id="create-root",
        )
    )
    first = values.runtime_event(root, identifier="runtime-10", source_sequence=10)
    inserted = await store.append_event(first)
    replayed = await store.append_event(first)
    changed_outbox = AtomicEventAppend(
        first.event,
        (
            OutboxIntent(
                "outbox-changed",
                "execution.timeline",
                "deliver-changed",
                CLOCK_NOW,
            ),
        ),
    )
    conflicted = await store.append_event(changed_outbox)
    older = await store.append_event(
        values.runtime_event(root, identifier="runtime-09", source_sequence=9)
    )
    second = await store.append_event(
        values.runtime_event(root, identifier="runtime-11", source_sequence=11)
    )

    assert inserted.status is AppendStatus.INSERTED and inserted.event is not None
    assert inserted.event.sequence == 2
    assert replayed.status is AppendStatus.REPLAYED
    assert replayed.event == inserted.event and replayed.outbox == inserted.outbox
    assert conflicted.status is AppendStatus.CONFLICT
    assert older.status is AppendStatus.REJECTED
    assert second.status is AppendStatus.INSERTED and second.event is not None
    assert second.event.sequence == 3
    assert [item.sequence for item in await store.list_events(values.scope, after_sequence=1)] == [
        2,
        3,
    ]

    invalid = values.runtime_event(root, identifier="invalid", source_sequence=12)
    before = await store.list_outbox(values.scope)
    rejected = await store.append_event(
        AtomicEventAppend(
            invalid.event,
            (
                OutboxIntent(
                    "outbox-invalid",
                    "execution.timeline",
                    invalid.event.ingestion_idempotency_key,
                    CLOCK_NOW,
                ),
            ),
        )
    )
    assert rejected.status is AppendStatus.REJECTED
    assert await store.list_outbox(values.scope) == before


__all__ = [
    "assert_atomic_replay_conflict_and_scope",
    "assert_concurrent_compare_and_swap_is_atomic",
    "assert_normalized_events_are_exact_and_monotonic",
]
