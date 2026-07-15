from __future__ import annotations

import asyncio
import inspect
import json
import pickle
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta

import pytest

from boltrig.fleet.application.grant_leases import (
    DurableRunScopedGrantBroker,
    GrantAuthenticationRejected,
    GrantAuthorityUnavailable,
)
from boltrig.fleet.domain.execution import PhaseAssignmentRef, PhaseRef
from boltrig.fleet.domain.grant_lease import (
    GrantAuthoritySnapshot,
    GrantLeaseBinding,
    GrantLeaseCandidate,
    GrantLeaseConflict,
    GrantLeaseStatus,
    GrantRequestObservation,
    StaleGrantGeneration,
    StoredGrantLease,
)
from boltrig.fleet.ports.credentials import (
    EphemeralBearer,
    IssuedGrant,
    RunScopedGrantBroker,
)
from boltrig.models import OrganisationUserRef
from tests.contracts.grant_lease_fixtures import authority_snapshot

from .grant_lease_store import MemoryGrantLeaseStore

NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)


class _Clock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


def _assignment(
    *,
    tenant: str = "tenant-1",
    workspace: str = "workspace-1",
    root: str = "root-1",
    phase: str = "phase-1",
    assignment: str = "assignment-1",
) -> PhaseAssignmentRef:
    return PhaseAssignmentRef(
        phase=PhaseRef(
            root_run_id=root,
            phase_id=phase,
            principal=OrganisationUserRef(tenant_id=tenant, user_id="user-1"),
            workspace_id=workspace,
        ),
        assignment_id=assignment,
    )


def _snapshot(
    assignment: PhaseAssignmentRef,
    *,
    policy_generation: int = 1,
    evaluation_id: str = "authority-1",
    evaluation_digest: str = "sha256:" + "a" * 64,
    permitted_verbs: tuple[str, ...] = ("document.read", "ticket.read"),
) -> GrantAuthoritySnapshot:
    return authority_snapshot(
        scope=GrantLeaseBinding.from_assignment(assignment),
        authority_evaluation_id=evaluation_id,
        authority_evaluation_digest=evaluation_digest,
        authority_policy_generation=policy_generation,
        permitted_verbs=permitted_verbs,
    )


def _broker(
    *,
    store: MemoryGrantLeaseStore | None = None,
    clock: _Clock | None = None,
    max_ttl_seconds: int = 120,
) -> tuple[DurableRunScopedGrantBroker, MemoryGrantLeaseStore, _Clock]:
    exact_store = store or MemoryGrantLeaseStore()
    exact_clock = clock or _Clock()
    broker = DurableRunScopedGrantBroker(
        exact_store,
        exact_store,
        clock=exact_clock,
        max_ttl_seconds=max_ttl_seconds,
    )
    compatibility: RunScopedGrantBroker = broker
    assert compatibility is broker
    return broker, exact_store, exact_clock


async def _activate(
    store: MemoryGrantLeaseStore,
    assignment: PhaseAssignmentRef,
    *,
    now: datetime = NOW,
    policy_generation: int = 1,
    evaluation_id: str = "authority-1",
    evaluation_digest: str = "sha256:" + "a" * 64,
    permitted_verbs: tuple[str, ...] = ("document.read", "ticket.read"),
) -> GrantAuthoritySnapshot:
    snapshot = _snapshot(
        assignment,
        policy_generation=policy_generation,
        evaluation_id=evaluation_id,
        evaluation_digest=evaluation_digest,
        permitted_verbs=permitted_verbs,
    )
    await store.install_authority_snapshot(snapshot, now=now)
    return snapshot


async def _issue(
    broker: DurableRunScopedGrantBroker,
    assignment: PhaseAssignmentRef,
    *,
    operation_id: str,
    expected_current_lease_generation: int | None = None,
    expires_at: datetime | None = None,
) -> IssuedGrant:
    return await broker.issue(
        assignment,
        expires_at=expires_at or NOW + timedelta(seconds=60),
        issue_operation_id=operation_id,
        expected_current_lease_generation=expected_current_lease_generation,
    )


def _observation(
    assignment: PhaseAssignmentRef,
    verb_id: str = "ticket.read",
) -> GrantRequestObservation:
    return GrantRequestObservation(assignment, verb_id)


@pytest.mark.invariant("SEC-152")
async def test_issue_uses_trusted_snapshot_and_persists_only_digest() -> None:
    broker, store, _clock = _broker()
    assignment = _assignment()
    snapshot = await _activate(store, assignment)

    issued = await _issue(broker, assignment, operation_id="issue-digest-only")
    token = issued.bearer_token.reveal()
    record = store.snapshot()[0]
    persisted = json.dumps(asdict(record), default=str, sort_keys=True)

    assert record.binding == GrantLeaseBinding.from_assignment(assignment)
    assert record.authority_snapshot == snapshot
    assert record.permitted_verbs == ("document.read", "ticket.read")
    assert (record.authority_policy_generation, record.lease_generation) == (1, 1)
    assert issued.lease.issue_operation_id == "issue-digest-only"
    assert record.token_digest not in {token, issued.lease.lease_id}
    assert token not in persisted
    assert token not in repr(record)
    assert token not in repr(issued)
    assert not hasattr(issued.bearer_token, "__dict__")
    with pytest.raises(TypeError, match="cannot be serialized"):
        pickle.dumps(issued)


def test_public_api_has_no_raw_authority_or_caller_time_parameters() -> None:
    issue = inspect.signature(DurableRunScopedGrantBroker.issue).parameters
    authenticate = inspect.signature(DurableRunScopedGrantBroker.authenticate).parameters
    active = inspect.signature(DurableRunScopedGrantBroker.is_active).parameters

    assert set(issue) == {
        "self",
        "assignment",
        "expires_at",
        "issue_operation_id",
        "expected_current_lease_generation",
    }
    assert set(authenticate) == {"self", "bearer", "observation"}
    assert set(active) == {"self", "lease_id", "assignment"}
    assert all(
        name not in issue
        for name in (
            "permitted_verbs",
            "authority_evaluation_id",
            "authority_evaluation_digest",
            "authority_policy_generation",
        )
    )


async def test_authentication_is_bound_to_every_observed_scope_component() -> None:
    broker, store, _clock = _broker()
    expected = _assignment()
    await _activate(store, expected)
    issued = await _issue(broker, expected, operation_id="issue-scope")

    for foreign in (
        _assignment(tenant="tenant-2"),
        _assignment(workspace="workspace-2"),
        _assignment(root="root-2"),
        _assignment(phase="phase-2"),
        _assignment(assignment="assignment-2"),
    ):
        with pytest.raises(GrantAuthenticationRejected, match="rejected"):
            await broker.authenticate(issued.bearer_token, _observation(foreign))
    assert await broker.authenticate(issued.bearer_token, _observation(expected))


async def test_only_current_trusted_observation_and_concrete_verb_authorize() -> None:
    broker, store, _clock = _broker()
    assignment = _assignment()
    await _activate(store, assignment)
    issued = await _issue(broker, assignment, operation_id="issue-current")

    for observation, bearer in (
        (_observation(assignment, "ticket.write"), issued.bearer_token),
        (_observation(assignment), EphemeralBearer("unrelated-secret")),
    ):
        with pytest.raises(GrantAuthenticationRejected, match="rejected"):
            await broker.authenticate(bearer, observation)
    for invalid in ("*", "ticket.*", "ticket.\N{CYRILLIC SMALL LETTER A}"):
        with pytest.raises(ValueError, match="concrete"):
            GrantRequestObservation(assignment, invalid)


async def test_expiry_uses_only_server_clock_and_ttl_is_bounded() -> None:
    broker, store, clock = _broker(max_ttl_seconds=60)
    assignment = _assignment()
    await _activate(store, assignment)
    issued = await _issue(broker, assignment, operation_id="issue-expiry")
    clock.advance(60)

    assert not await broker.is_active(issued.lease.lease_id, assignment)
    with pytest.raises(GrantAuthenticationRejected, match="rejected"):
        await broker.authenticate(issued.bearer_token, _observation(assignment))
    assert store.snapshot()[0].status is GrantLeaseStatus.EXPIRED
    with pytest.raises(ValueError, match="TTL"):
        await _issue(
            broker,
            assignment,
            operation_id="issue-too-long",
            expected_current_lease_generation=1,
            expires_at=clock.value + timedelta(seconds=61),
        )


async def test_concurrent_initial_issue_has_one_store_cas_winner() -> None:
    broker, store, _clock = _broker()
    assignment = _assignment()
    await _activate(store, assignment)

    attempts = await asyncio.gather(
        _issue(broker, assignment, operation_id="issue-race-a"),
        _issue(broker, assignment, operation_id="issue-race-b"),
        return_exceptions=True,
    )

    assert sum(isinstance(item, IssuedGrant) for item in attempts) == 1
    assert sum(isinstance(item, StaleGrantGeneration) for item in attempts) == 1
    winner = next(item for item in attempts if isinstance(item, IssuedGrant))
    assert winner.lease.lease_generation == 1


async def test_explicit_same_authority_reissue_advances_only_lease_generation() -> None:
    broker, store, _clock = _broker()
    assignment = _assignment()
    await _activate(store, assignment)
    first = await _issue(broker, assignment, operation_id="issue-generation-1")
    second = await _issue(
        broker,
        assignment,
        operation_id="issue-generation-2",
        expected_current_lease_generation=first.lease.lease_generation,
    )

    assert (
        first.lease.authority_policy_generation,
        second.lease.authority_policy_generation,
    ) == (1, 1)
    assert (first.lease.lease_generation, second.lease.lease_generation) == (1, 2)
    with pytest.raises(GrantAuthenticationRejected, match="rejected"):
        await broker.authenticate(first.bearer_token, _observation(assignment))
    assert await broker.authenticate(second.bearer_token, _observation(assignment))
    with pytest.raises(StaleGrantGeneration):
        await _issue(
            broker,
            assignment,
            operation_id="issue-stale-cas",
            expected_current_lease_generation=1,
        )


async def test_policy_rollover_invalidates_old_lease_before_new_issue() -> None:
    broker, store, _clock = _broker()
    assignment = _assignment()
    await _activate(store, assignment)
    first = await _issue(broker, assignment, operation_id="issue-policy-1")
    await _activate(
        store,
        assignment,
        policy_generation=2,
        evaluation_id="authority-2",
        evaluation_digest="sha256:" + "b" * 64,
        permitted_verbs=("document.read",),
    )

    with pytest.raises(GrantAuthenticationRejected, match="rejected"):
        await broker.authenticate(first.bearer_token, _observation(assignment))
    second = await _issue(
        broker,
        assignment,
        operation_id="issue-policy-2",
        expected_current_lease_generation=first.lease.lease_generation,
    )
    assert (second.lease.authority_policy_generation, second.lease.lease_generation) == (
        2,
        2,
    )
    with pytest.raises(GrantAuthenticationRejected, match="rejected"):
        await broker.authenticate(second.bearer_token, _observation(assignment))
    assert await broker.authenticate(
        second.bearer_token,
        _observation(assignment, "document.read"),
    )


@pytest.mark.invariant("SEC-152")
async def test_exact_and_assignment_cancellation_revoke_immediately() -> None:
    broker, store, _clock = _broker()
    assignment = _assignment()
    await _activate(store, assignment)
    issued = await _issue(broker, assignment, operation_id="issue-cancel")

    await broker.revoke_bound(
        issued.lease.lease_id,
        _assignment(assignment="foreign-assignment"),
        reason="operator_cancelled",
    )
    assert await broker.authenticate(issued.bearer_token, _observation(assignment))
    assert await broker.cancel_assignment(assignment) == 1
    results = await asyncio.gather(
        *(broker.authenticate(issued.bearer_token, _observation(assignment)) for _ in range(20)),
        return_exceptions=True,
    )
    assert all(isinstance(item, GrantAuthenticationRejected) for item in results)
    record = store.snapshot()[0]
    assert (record.status, record.revocation_reason) == (
        GrantLeaseStatus.REVOKED,
        "assignment_cancelled",
    )


async def test_operator_revoke_requires_exact_assignment_scope() -> None:
    broker, store, _clock = _broker()
    assignment = _assignment()
    await _activate(store, assignment)
    issued = await _issue(broker, assignment, operation_id="issue-operator-revoke")

    await broker.revoke(
        issued.lease.lease_id,
        _assignment(tenant="tenant-foreign"),
        reason="operator_cancelled",
    )
    assert await broker.authenticate(issued.bearer_token, _observation(assignment))
    await broker.revoke(issued.lease.lease_id, assignment, reason="operator_cancelled")
    with pytest.raises(GrantAuthenticationRejected, match="rejected"):
        await broker.authenticate(issued.bearer_token, _observation(assignment))


@pytest.mark.parametrize(
    "reason",
    ("x" * 161, "invalid\nreason", "invalid\x7freason", "invalid\x85reason", "\ud800"),
)
async def test_revocation_reason_matches_bounded_utf8_policy(reason: str) -> None:
    broker, store, _clock = _broker()
    assignment = _assignment()
    await _activate(store, assignment)
    issued = await _issue(broker, assignment, operation_id=f"issue-reason-{len(reason)}")

    with pytest.raises(ValueError, match="reason|UTF-8"):
        await broker.revoke(issued.lease.lease_id, assignment, reason=reason)
    assert await broker.authenticate(issued.bearer_token, _observation(assignment))


async def test_root_revocation_is_tenant_workspace_and_root_scoped() -> None:
    broker, store, _clock = _broker()
    assignments = (
        _assignment(assignment="assignment-1"),
        _assignment(phase="phase-2", assignment="assignment-2"),
        _assignment(root="root-2", assignment="assignment-3"),
        _assignment(workspace="workspace-2", assignment="assignment-4"),
    )
    for assignment in assignments:
        await _activate(store, assignment)
    issued = tuple(
        [
            await _issue(broker, assignment, operation_id=f"issue-root-{index}")
            for index, assignment in enumerate(assignments, start=1)
        ]
    )

    assert await broker.cancel_root("tenant-1", "workspace-1", "root-1") == 2
    for grant, assignment in zip(issued[:2], assignments[:2], strict=True):
        with pytest.raises(GrantAuthenticationRejected, match="rejected"):
            await broker.authenticate(grant.bearer_token, _observation(assignment))
    for grant, assignment in zip(issued[2:], assignments[2:], strict=True):
        assert await broker.authenticate(grant.bearer_token, _observation(assignment))


async def test_missing_or_suspended_authority_fails_closed() -> None:
    broker, store, _clock = _broker()
    assignment = _assignment()

    with pytest.raises(GrantAuthorityUnavailable, match="unavailable"):
        await _issue(broker, assignment, operation_id="issue-no-authority")
    await _activate(store, assignment)
    issued = await _issue(broker, assignment, operation_id="issue-before-suspend")
    assert (
        await store.suspend_grant_authority(
            GrantLeaseBinding.from_assignment(assignment),
            now=NOW,
        )
        == 1
    )
    with pytest.raises(GrantAuthenticationRejected, match="rejected"):
        await broker.authenticate(issued.bearer_token, _observation(assignment))


class _UnknownCommitStore(MemoryGrantLeaseStore):
    async def insert_active(
        self,
        candidate: GrantLeaseCandidate,
        *,
        expected_authority: GrantAuthoritySnapshot,
        now: datetime,
    ) -> StoredGrantLease:
        await super().insert_active(
            candidate,
            expected_authority=expected_authority,
            now=now,
        )
        raise RuntimeError("simulated lost commit acknowledgement")


class _AdvanceClockOnAuthorityResolutionStore(MemoryGrantLeaseStore):
    def __init__(self, clock: _Clock) -> None:
        super().__init__()
        self.clock = clock
        self.advance_next_seconds = 0

    async def resolve_current_grant_authority(
        self,
        assignment: PhaseAssignmentRef,
        *,
        at: datetime,
    ) -> GrantAuthoritySnapshot | None:
        snapshot = await super().resolve_current_grant_authority(assignment, at=at)
        advance = self.advance_next_seconds
        self.advance_next_seconds = 0
        self.clock.advance(advance)
        return snapshot


async def test_server_time_is_refreshed_after_awaited_authority_resolution() -> None:
    clock = _Clock()
    store = _AdvanceClockOnAuthorityResolutionStore(clock)
    broker, _store, _clock = _broker(store=store, clock=clock, max_ttl_seconds=60)
    assignment = _assignment()
    await _activate(store, assignment)

    store.advance_next_seconds = 61
    with pytest.raises(ValueError, match="TTL"):
        await _issue(broker, assignment, operation_id="issue-delayed-authority")
    assert store.snapshot() == ()

    clock.value = NOW
    issued = await _issue(broker, assignment, operation_id="issue-before-delay")
    store.advance_next_seconds = 61
    with pytest.raises(GrantAuthenticationRejected, match="rejected"):
        await broker.authenticate(issued.bearer_token, _observation(assignment))
    assert store.snapshot()[0].status is GrantLeaseStatus.EXPIRED


class _BlockUnknownCommitReceiptStore(_UnknownCommitStore):
    def __init__(self) -> None:
        super().__init__()
        self.receipt_entered = asyncio.Event()
        self.release_receipt = asyncio.Event()
        self._block_next_receipt = True

    async def get_by_issue_operation_id(
        self,
        issue_operation_id: str,
        binding: GrantLeaseBinding,
    ) -> StoredGrantLease | None:
        if self._block_next_receipt:
            self._block_next_receipt = False
            self.receipt_entered.set()
            await self.release_receipt.wait()
        return await super().get_by_issue_operation_id(issue_operation_id, binding)


async def test_cancellation_during_unknown_commit_receipt_revokes_receipt() -> None:
    store = _BlockUnknownCommitReceiptStore()
    broker, _store, _clock = _broker(store=store)
    assignment = _assignment()
    await _activate(store, assignment)
    task = asyncio.create_task(
        _issue(broker, assignment, operation_id="issue-cancel-during-receipt")
    )
    await store.receipt_entered.wait()

    task.cancel()
    task.cancel()
    store.release_receipt.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    receipt = await store.get_by_issue_operation_id(
        "issue-cancel-during-receipt",
        GrantLeaseBinding.from_assignment(assignment),
    )
    assert receipt is not None
    assert (receipt.status, receipt.revocation_reason) == (
        GrantLeaseStatus.REVOKED,
        "issue_cancelled",
    )


async def test_unknown_commit_reconciles_exact_operation_receipt() -> None:
    store = _UnknownCommitStore()
    broker, _store, _clock = _broker(store=store)
    assignment = _assignment()
    await _activate(store, assignment)

    issued = await _issue(broker, assignment, operation_id="issue-unknown-commit")

    assert issued.lease.lease_generation == 1
    assert await broker.authenticate(issued.bearer_token, _observation(assignment))


class _CommitThenBlockStore(MemoryGrantLeaseStore):
    def __init__(self) -> None:
        super().__init__()
        self.committed = asyncio.Event()
        self.release = asyncio.Event()

    async def insert_active(
        self,
        candidate: GrantLeaseCandidate,
        *,
        expected_authority: GrantAuthoritySnapshot,
        now: datetime,
    ) -> StoredGrantLease:
        stored = await super().insert_active(
            candidate,
            expected_authority=expected_authority,
            now=now,
        )
        self.committed.set()
        await self.release.wait()
        return stored


class _BlockActiveProjectionStore(MemoryGrantLeaseStore):
    def __init__(self) -> None:
        super().__init__()
        self.projection_entered = asyncio.Event()
        self.release_projection = asyncio.Event()

    async def find_active_by_id(
        self,
        lease_id: str,
        binding: GrantLeaseBinding,
        *,
        now: datetime,
        expected_authority: GrantAuthoritySnapshot,
    ) -> StoredGrantLease | None:
        self.projection_entered.set()
        await self.release_projection.wait()
        return await super().find_active_by_id(
            lease_id,
            binding,
            now=now,
            expected_authority=expected_authority,
        )


class _FailActiveProjectionStore(MemoryGrantLeaseStore):
    async def find_active_by_id(
        self,
        lease_id: str,
        binding: GrantLeaseBinding,
        *,
        now: datetime,
        expected_authority: GrantAuthoritySnapshot,
    ) -> StoredGrantLease | None:
        raise RuntimeError("simulated post-commit projection read failure")


async def test_post_commit_projection_failure_revokes_before_reraising() -> None:
    store = _FailActiveProjectionStore()
    broker, _store, _clock = _broker(store=store)
    assignment = _assignment()
    await _activate(store, assignment)

    with pytest.raises(RuntimeError, match="projection read failure"):
        await _issue(broker, assignment, operation_id="issue-failed-projection-read")

    receipt = await store.get_by_issue_operation_id(
        "issue-failed-projection-read",
        GrantLeaseBinding.from_assignment(assignment),
    )
    assert receipt is not None
    assert (receipt.status, receipt.revocation_reason) == (
        GrantLeaseStatus.REVOKED,
        "issue_failed",
    )


async def test_cancellation_during_post_commit_projection_revokes_receipt() -> None:
    store = _BlockActiveProjectionStore()
    broker, _store, _clock = _broker(store=store)
    assignment = _assignment()
    await _activate(store, assignment)
    task = asyncio.create_task(
        _issue(broker, assignment, operation_id="issue-cancel-during-projection")
    )
    await store.projection_entered.wait()

    task.cancel()
    task.cancel()
    store.release_projection.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    receipt = await store.get_by_issue_operation_id(
        "issue-cancel-during-projection",
        GrantLeaseBinding.from_assignment(assignment),
    )
    assert receipt is not None
    assert (receipt.status, receipt.revocation_reason) == (
        GrantLeaseStatus.REVOKED,
        "issue_cancelled",
    )


async def test_cancellation_after_commit_reconciles_and_revokes_receipt() -> None:
    store = _CommitThenBlockStore()
    broker, _store, _clock = _broker(store=store)
    assignment = _assignment()
    await _activate(store, assignment)
    task = asyncio.create_task(_issue(broker, assignment, operation_id="issue-cancel-after-commit"))
    await store.committed.wait()

    task.cancel()
    task.cancel()
    store.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    receipt = await store.get_by_issue_operation_id(
        "issue-cancel-after-commit",
        GrantLeaseBinding.from_assignment(assignment),
    )
    assert receipt is not None
    assert (receipt.status, receipt.revocation_reason) == (
        GrantLeaseStatus.REVOKED,
        "issue_cancelled",
    )


class _UnknownCommitThenBlockStore(_CommitThenBlockStore):
    async def insert_active(
        self,
        candidate: GrantLeaseCandidate,
        *,
        expected_authority: GrantAuthoritySnapshot,
        now: datetime,
    ) -> StoredGrantLease:
        await super().insert_active(
            candidate,
            expected_authority=expected_authority,
            now=now,
        )
        raise RuntimeError("simulated unknown commit during cancellation")


async def test_cancelled_unknown_commit_revokes_by_exact_operation_receipt() -> None:
    store = _UnknownCommitThenBlockStore()
    broker, _store, _clock = _broker(store=store)
    assignment = _assignment()
    await _activate(store, assignment)
    task = asyncio.create_task(
        _issue(broker, assignment, operation_id="issue-cancel-unknown-commit")
    )
    await store.committed.wait()

    task.cancel()
    store.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    receipt = await store.get_by_issue_operation_id(
        "issue-cancel-unknown-commit",
        GrantLeaseBinding.from_assignment(assignment),
    )
    assert receipt is not None
    assert (receipt.status, receipt.revocation_reason) == (
        GrantLeaseStatus.REVOKED,
        "issue_cancelled",
    )


class _BlockBeforeCommitStore(MemoryGrantLeaseStore):
    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def insert_active(
        self,
        candidate: GrantLeaseCandidate,
        *,
        expected_authority: GrantAuthoritySnapshot,
        now: datetime,
    ) -> StoredGrantLease:
        self.entered.set()
        await self.release.wait()
        return await super().insert_active(
            candidate,
            expected_authority=expected_authority,
            now=now,
        )


async def test_cancellation_before_commit_observes_completion_then_revokes() -> None:
    store = _BlockBeforeCommitStore()
    broker, _store, _clock = _broker(store=store)
    assignment = _assignment()
    await _activate(store, assignment)
    task = asyncio.create_task(
        _issue(broker, assignment, operation_id="issue-cancel-before-commit")
    )
    await store.entered.wait()

    task.cancel()
    store.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    receipt = await store.get_by_issue_operation_id(
        "issue-cancel-before-commit",
        GrantLeaseBinding.from_assignment(assignment),
    )
    assert receipt is not None
    assert (receipt.status, receipt.revocation_reason) == (
        GrantLeaseStatus.REVOKED,
        "issue_cancelled",
    )


async def test_reusing_operation_id_never_hands_out_a_different_bearer() -> None:
    broker, store, _clock = _broker()
    assignment = _assignment()
    await _activate(store, assignment)
    first = await _issue(broker, assignment, operation_id="issue-process-local")

    with pytest.raises(GrantLeaseConflict, match="operation conflicts"):
        await _issue(broker, assignment, operation_id="issue-process-local")

    assert await broker.authenticate(first.bearer_token, _observation(assignment))
    assert len(store.snapshot()) == 1


class _InvalidProjectionStore(MemoryGrantLeaseStore):
    async def insert_active(
        self,
        candidate: GrantLeaseCandidate,
        *,
        expected_authority: GrantAuthoritySnapshot,
        now: datetime,
    ) -> StoredGrantLease:
        stored = await super().insert_active(
            candidate,
            expected_authority=expected_authority,
            now=now,
        )
        return replace(stored, lease_generation=stored.lease_generation + 1)


async def test_invalid_store_projection_is_revoked_before_bearer_handoff() -> None:
    store = _InvalidProjectionStore()
    broker, _store, _clock = _broker(store=store)
    assignment = _assignment()
    await _activate(store, assignment)

    with pytest.raises(GrantLeaseConflict, match="invalid issue projection"):
        await _issue(broker, assignment, operation_id="issue-invalid-projection")

    record = store.snapshot()[0]
    assert (record.status, record.revocation_reason) == (
        GrantLeaseStatus.REVOKED,
        "invalid_issue_projection",
    )
