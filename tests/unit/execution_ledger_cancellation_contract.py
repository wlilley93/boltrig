"""Reusable cancellation, terminal ordering, and retry-chain contracts."""

from __future__ import annotations

from dataclasses import replace

from boltrig.fleet.ports.execution_ledger import ExecutionLedgerStore
from boltrig.models import (
    AssignmentStatus,
    CancellationMetadata,
    ExecutionPhaseStatus,
    LedgerCommandKind,
    LedgerMutationStatus,
    LedgerWorkItemStatus,
    PhaseTerminalOutcome,
    RootRunStatus,
)

from .execution_ledger_fixtures import LedgerValues, NOW, digest
from .execution_ledger_lifecycle_contract import seed_running_work


async def assert_cancellation_retry_and_terminal_ordering(
    store: ExecutionLedgerStore,
) -> None:
    values = LedgerValues()
    await seed_running_work(store, values)
    root = await store.get_root(values.scope)
    phase = await store.get_phase(values.scope, "phase-a")
    work = await store.get_work_item(values.scope, "work-a")
    assignment = await store.get_assignment(values.scope, "assignment-1")
    assert root is not None and phase is not None and work is not None and assignment is not None
    cancellation = CancellationMetadata(
        values.principal, "user.requested", NOW, digest("cancel-detail")
    )

    premature_work = await store.commit(
        values.write(
            replace(work, status=LedgerWorkItemStatus.CANCELLED, version=3),
            LedgerCommandKind.CANCEL,
            expected_version=2,
            command_id="premature-cancel-work",
        )
    )
    assert premature_work.status is LedgerMutationStatus.REJECTED
    cancelling_root = replace(
        root,
        status=RootRunStatus.CANCELLING,
        cancellation=cancellation,
        version=3,
    )
    assert (
        await store.commit(
            values.write(
                cancelling_root,
                LedgerCommandKind.CANCEL,
                expected_version=2,
                command_id="cancel-root",
            )
        )
    ).status is LedgerMutationStatus.APPLIED
    premature_root = await store.commit(
        values.write(
            replace(cancelling_root, status=RootRunStatus.CANCELLED, version=4),
            LedgerCommandKind.CANCEL,
            expected_version=3,
            command_id="premature-finish-cancel",
        )
    )
    assert premature_root.status is LedgerMutationStatus.REJECTED

    cancelled_assignment = replace(
        assignment, status=AssignmentStatus.CANCELLED, version=4
    )
    assert (
        await store.commit(
            values.write(
                cancelled_assignment,
                LedgerCommandKind.CANCEL,
                expected_version=3,
                command_id="cancel-assignment",
            )
        )
    ).status is LedgerMutationStatus.APPLIED
    cancelled_work = replace(work, status=LedgerWorkItemStatus.CANCELLED, version=3)
    assert (
        await store.commit(
            values.write(
                cancelled_work,
                LedgerCommandKind.CANCEL,
                expected_version=2,
                command_id="cancel-work",
            )
        )
    ).status is LedgerMutationStatus.APPLIED
    interrupting = replace(
        phase, status=ExecutionPhaseStatus.INTERRUPTING, version=4
    )
    assert (
        await store.commit(
            values.write(
                interrupting,
                LedgerCommandKind.CANCEL,
                expected_version=3,
                command_id="interrupt-phase",
            )
        )
    ).status is LedgerMutationStatus.APPLIED
    interrupted = replace(
        interrupting,
        status=ExecutionPhaseStatus.INTERRUPTED,
        terminal_outcome=PhaseTerminalOutcome("cancelled", digest("cancelled"), NOW),
        version=5,
    )
    assert (
        await store.commit(
            values.write(
                interrupted,
                LedgerCommandKind.CANCEL,
                expected_version=4,
                command_id="finish-interrupt",
            )
        )
    ).status is LedgerMutationStatus.APPLIED
    assert (
        await store.commit(
            values.write(
                replace(cancelling_root, status=RootRunStatus.CANCELLED, version=4),
                LedgerCommandKind.CANCEL,
                expected_version=3,
                command_id="finish-cancel",
            )
        )
    ).status is LedgerMutationStatus.APPLIED

    retry = LedgerValues(run="run-retry")
    await seed_running_work(store, retry)
    first = await store.get_assignment(retry.scope, "assignment-1")
    assert first is not None
    failed = replace(first, status=AssignmentStatus.FAILED, version=4)
    assert (
        await store.commit(
            retry.write(
                failed,
                LedgerCommandKind.TRANSITION_STATUS,
                expected_version=3,
                command_id="fail-first-attempt",
            )
        )
    ).status is LedgerMutationStatus.APPLIED
    replacement = retry.assignment(attempt=2, replaces="assignment-1")
    assert (
        await store.commit(
            retry.write(
                replacement,
                LedgerCommandKind.REPLACE_ASSIGNMENT,
                expected_version=0,
                command_id="replace-attempt",
            )
        )
    ).status is LedgerMutationStatus.APPLIED
    fork = replace(replacement, id="assignment-fork")
    assert (
        await store.commit(
            retry.write(
                fork,
                LedgerCommandKind.REPLACE_ASSIGNMENT,
                expected_version=0,
                command_id="fork-attempt",
            )
        )
    ).status is LedgerMutationStatus.CONFLICT


__all__ = ["assert_cancellation_retry_and_terminal_ordering"]
