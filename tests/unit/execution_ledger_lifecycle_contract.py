"""Reusable hierarchy, lifecycle, cancellation, and runtime binding contracts."""

from __future__ import annotations

from dataclasses import replace

from boltrig.fleet.ports.execution_ledger import AppendStatus, ExecutionLedgerStore
from boltrig.models import (
    AssignmentStatus,
    CodexBindingKind,
    CodexItemBinding,
    CodexThreadBinding,
    CodexTurnBinding,
    ExecutionPhaseStatus,
    LedgerCommandKind,
    LedgerMutationStatus,
    LedgerWorkItemStatus,
    PhaseTerminalOutcome,
    RootRunStatus,
    RuntimeIdentity,
    RuntimeIdentityStatus,
    VerificationCheck,
    VerificationStatus,
    VerifierKind,
    VerifierRef,
)

from .execution_ledger_fixtures import CLOCK_NOW, LedgerValues, NOW, digest


async def seed_running_work(
    store: ExecutionLedgerStore,
    values: LedgerValues,
    *,
    include_assignment: bool = True,
) -> None:
    root = values.root()
    await _applied(
        store,
        values.write(
            root,
            LedgerCommandKind.CREATE_ROOT,
            expected_version=0,
            command_id=f"{values.run}-create-root",
        ),
    )
    await _applied(
        store,
        values.write(
            replace(root, status=RootRunStatus.RUNNING, version=2),
            LedgerCommandKind.TRANSITION_STATUS,
            expected_version=1,
            command_id=f"{values.run}-start-root",
        ),
    )
    phase = values.phase()
    await _applied(
        store,
        values.write(
            phase,
            LedgerCommandKind.CREATE_PHASE,
            expected_version=0,
            command_id=f"{values.run}-create-phase",
        ),
    )
    starting = replace(phase, status=ExecutionPhaseStatus.STARTING, version=2)
    await _applied(
        store,
        values.write(
            starting,
            LedgerCommandKind.TRANSITION_STATUS,
            expected_version=1,
            command_id=f"{values.run}-start-phase",
        ),
    )
    await _applied(
        store,
        values.write(
            replace(starting, status=ExecutionPhaseStatus.RUNNING, version=3),
            LedgerCommandKind.TRANSITION_STATUS,
            expected_version=2,
            command_id=f"{values.run}-run-phase",
        ),
    )
    work = values.work()
    await _applied(
        store,
        values.write(
            work,
            LedgerCommandKind.ENQUEUE_WORK,
            expected_version=0,
            command_id=f"{values.run}-create-work",
        ),
    )
    await _applied(
        store,
        values.write(
            replace(work, status=LedgerWorkItemStatus.IN_FLIGHT, version=2),
            LedgerCommandKind.TRANSITION_STATUS,
            expected_version=1,
            command_id=f"{values.run}-start-work",
        ),
    )
    identity = values.identity()
    identity_status = (await store.write_runtime_identity(identity, expected_generation=0)).status
    assert identity_status in {AppendStatus.INSERTED, AppendStatus.REPLAYED}
    if not include_assignment:
        return
    assignment = values.assignment()
    await _applied(
        store,
        values.write(
            assignment,
            LedgerCommandKind.ASSIGN_WORK,
            expected_version=0,
            command_id=f"{values.run}-assign-work",
        ),
    )
    claimed = replace(
        assignment,
        status=AssignmentStatus.CLAIMED,
        lease=values.lease(),
        version=2,
    )
    await _applied(
        store,
        values.write(
            claimed,
            LedgerCommandKind.TRANSITION_STATUS,
            expected_version=1,
            command_id=f"{values.run}-claim-work",
        ),
    )
    await _applied(
        store,
        values.write(
            replace(claimed, status=AssignmentStatus.RUNNING, version=3),
            LedgerCommandKind.TRANSITION_STATUS,
            expected_version=2,
            command_id=f"{values.run}-run-work",
        ),
    )


async def assert_assignment_authority_matches_phase_policy(
    store: ExecutionLedgerStore,
) -> None:
    values = LedgerValues()
    await seed_running_work(store, values, include_assignment=False)
    mismatch = values.assignment(authority_policy_generation=4)
    rejected = await store.commit(
        values.write(
            mismatch,
            LedgerCommandKind.ASSIGN_WORK,
            expected_version=0,
            command_id="reject-mismatched-authority-policy",
        )
    )

    assert rejected.status is LedgerMutationStatus.REJECTED
    assert await store.get_assignment(values.scope, mismatch.id) is None
    valid = values.assignment()
    await _applied(
        store,
        values.write(
            valid,
            LedgerCommandKind.ASSIGN_WORK,
            expected_version=0,
            command_id="accept-current-authority-policy",
        ),
    )


async def assert_hierarchy_lifecycle_and_atomic_outbox(
    store: ExecutionLedgerStore,
) -> None:
    values = LedgerValues()
    orphan_phase = await store.commit(
        values.write(
            values.phase(),
            LedgerCommandKind.CREATE_PHASE,
            expected_version=0,
            command_id="orphan-phase",
        )
    )
    assert orphan_phase.status is LedgerMutationStatus.NOT_FOUND
    assert await store.get_phase(values.scope, "phase-a") is None
    assert await store.list_events(values.scope) == ()
    assert await store.list_outbox(values.scope) == ()

    await seed_running_work(store, values)
    assignment = await store.get_assignment(values.scope, "assignment-1")
    assert assignment is not None
    premature = await store.commit(
        values.write(
            replace(values.work(), status=LedgerWorkItemStatus.DONE, version=3),
            LedgerCommandKind.TRANSITION_STATUS,
            expected_version=2,
            command_id="premature-done",
        )
    )
    assert premature.status is LedgerMutationStatus.REJECTED

    result = values.result()
    await _applied(
        store,
        values.write(
            result,
            LedgerCommandKind.RECORD_RESULT,
            expected_version=0,
            command_id="record-result",
        ),
    )
    await _applied(
        store,
        values.write(
            replace(assignment, status=AssignmentStatus.COMPLETED, version=4),
            LedgerCommandKind.TRANSITION_STATUS,
            expected_version=3,
            command_id="complete-assignment",
        ),
    )
    verification = values.verification()
    await _applied(
        store,
        values.write(
            verification,
            LedgerCommandKind.RECORD_VERIFICATION,
            expected_version=0,
            command_id="record-verification",
        ),
    )
    passed = replace(
        verification,
        status=VerificationStatus.PASSED,
        checks=(VerificationCheck("checks.pass", True),),
        verified_by=VerifierRef(VerifierKind.SYSTEM, system_id="verifier-v1"),
    )
    await _applied(
        store,
        values.write(
            passed,
            LedgerCommandKind.TRANSITION_STATUS,
            expected_version=1,
            command_id="pass-verification",
        ),
    )
    current_work = await store.get_work_item(values.scope, "work-a")
    assert current_work is not None
    verifying = replace(current_work, status=LedgerWorkItemStatus.VERIFYING, version=3)
    await _applied(
        store,
        values.write(
            verifying,
            LedgerCommandKind.TRANSITION_STATUS,
            expected_version=2,
            command_id="verify-work",
        ),
    )
    await _applied(
        store,
        values.write(
            replace(verifying, status=LedgerWorkItemStatus.DONE, version=4),
            LedgerCommandKind.TRANSITION_STATUS,
            expected_version=3,
            command_id="finish-work",
        ),
    )
    current_phase = await store.get_phase(values.scope, "phase-a")
    assert current_phase is not None
    phase_verifying = replace(current_phase, status=ExecutionPhaseStatus.VERIFYING, version=4)
    await _applied(
        store,
        values.write(
            phase_verifying,
            LedgerCommandKind.TRANSITION_STATUS,
            expected_version=3,
            command_id="verify-phase",
        ),
    )
    succeeded_phase = replace(
        phase_verifying,
        status=ExecutionPhaseStatus.SUCCEEDED,
        terminal_outcome=PhaseTerminalOutcome("completed", digest("phase-result"), NOW),
        version=5,
    )
    await _applied(
        store,
        values.write(
            succeeded_phase,
            LedgerCommandKind.TRANSITION_STATUS,
            expected_version=4,
            command_id="finish-phase",
        ),
    )
    root = await store.get_root(values.scope)
    assert root is not None
    await _applied(
        store,
        values.write(
            replace(
                root,
                status=RootRunStatus.SUCCEEDED,
                final_synthesis_digest=digest("synthesis"),
                version=3,
            ),
            LedgerCommandKind.TRANSITION_STATUS,
            expected_version=2,
            command_id="finish-root",
        ),
    )
    events = await store.list_events(values.scope)
    outbox = await store.list_outbox(values.scope)
    assert [item.sequence for item in events] == list(range(1, len(events) + 1))
    assert len(events) == len(outbox)


async def assert_runtime_identity_and_binding_ownership(
    store: ExecutionLedgerStore,
) -> None:
    values = LedgerValues()
    await seed_running_work(store, values)
    thread = values.thread()
    inserted = await store.append_binding(thread)
    assert inserted.status is AppendStatus.INSERTED
    assert (await store.append_binding(thread)).status is AppendStatus.REPLAYED
    assert (
        await store.append_binding(values.thread(thread_id="second-phase-thread"))
    ).status is AppendStatus.CONFLICT

    turn = CodexTurnBinding(
        values.scope,
        thread,
        CodexBindingKind.PHASE,
        "turn-a",
        bound_at=NOW,
    )
    assert (await store.append_binding(turn)).status is AppendStatus.INSERTED
    missing_parent_turn = CodexTurnBinding(
        values.scope,
        thread,
        CodexBindingKind.NATIVE_OBSERVATION,
        "turn-native",
        "missing-turn",
        NOW,
    )
    assert (await store.append_binding(missing_parent_turn)).status is AppendStatus.NOT_FOUND
    item = CodexItemBinding(
        values.scope,
        turn,
        CodexBindingKind.PHASE,
        "item-a",
        bound_at=NOW,
    )
    assert (await store.append_binding(item)).status is AppendStatus.INSERTED
    child_thread = CodexThreadBinding(
        values.scope,
        "phase-a",
        "assignment-1",
        "runtime-a",
        CodexBindingKind.NATIVE_OBSERVATION,
        "thread-native",
        thread.thread_id,
        NOW,
    )
    assert (await store.append_binding(child_thread)).status is AppendStatus.INSERTED

    other = LedgerValues("org-b", "workspace-b", "run-b")
    same_id = other.identity(identity_id="runtime-a")
    assert (
        await store.write_runtime_identity(same_id, expected_generation=0)
    ).status is AppendStatus.INSERTED
    assert await store.get_runtime_identity(other.scope.workspace, "runtime-a") == same_id
    assert await store.get_runtime_identity(values.scope.workspace, "runtime-a") != same_id

    identity = values.identity()
    revoked = RuntimeIdentity(
        identity.id,
        identity.principal,
        identity.workspace,
        2,
        RuntimeIdentityStatus.REVOKED,
        identity.created_at,
        CLOCK_NOW,
    )
    assert (
        await store.write_runtime_identity(revoked, expected_generation=1)
    ).status is AppendStatus.INSERTED
    assert (
        await store.write_runtime_identity(revoked, expected_generation=1)
    ).status is AppendStatus.REPLAYED
    assert (
        await store.write_runtime_identity(revoked, expected_generation=2)
    ).status is AppendStatus.CONFLICT
    new_item = replace(item, item_id="item-after-revocation")
    assert (await store.append_binding(new_item)).status is AppendStatus.REJECTED


async def _applied(store: ExecutionLedgerStore, write: object) -> None:
    from boltrig.fleet.ports.execution_ledger import AtomicLedgerWrite

    assert type(write) is AtomicLedgerWrite
    outcome = await store.commit(write)
    assert outcome.status is LedgerMutationStatus.APPLIED


__all__ = [
    "assert_assignment_authority_matches_phase_policy",
    "assert_hierarchy_lifecycle_and_atomic_outbox",
    "assert_runtime_identity_and_binding_ownership",
    "seed_running_work",
]
