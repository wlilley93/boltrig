from __future__ import annotations

import asyncio
import json
import pickle
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

import pytest

from boltrig.fleet.application.grant_leases import (
    DurableRunScopedGrantBroker,
    GrantAuthenticationRejected,
)
from boltrig.fleet.domain.execution import (
    PhaseAssignmentRef,
    PhaseRef,
)
from boltrig.fleet.domain.grant_lease import (
    ActiveGrantGenerationConflict,
    GrantLeaseBinding,
    GrantLeaseStatus,
    StaleGrantGeneration,
)
from boltrig.fleet.ports.credentials import EphemeralBearer, IssuedGrant, RunScopedGrantBroker
from boltrig.models import OrganisationUserRef

from .grant_lease_store import MemoryGrantLeaseStore

NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)
AUTHORITY_EVALUATION_ID = "authority-evaluation-1"
AUTHORITY_EVALUATION_DIGEST = "sha256:" + "a" * 64


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


def _broker(
    *, max_ttl_seconds: int = 120
) -> tuple[DurableRunScopedGrantBroker, MemoryGrantLeaseStore, _Clock]:
    store = MemoryGrantLeaseStore()
    clock = _Clock()
    broker = DurableRunScopedGrantBroker(
        store, clock=clock, max_ttl_seconds=max_ttl_seconds
    )
    compatibility: RunScopedGrantBroker = broker
    assert compatibility is broker
    return broker, store, clock


async def _issue(
    broker: DurableRunScopedGrantBroker,
    assignment: PhaseAssignmentRef,
    *,
    generation: int = 1,
) -> IssuedGrant:
    return await broker.issue(
        assignment,
        expires_at=NOW + timedelta(seconds=60),
        policy_generation=generation,
        permitted_verbs=("document.read", "ticket.read"),
        authority_evaluation_id=AUTHORITY_EVALUATION_ID,
        authority_evaluation_digest=AUTHORITY_EVALUATION_DIGEST,
    )


@pytest.mark.invariant("SEC-152")
async def test_issue_persists_only_digest_and_returns_redacted_ephemeral_bearer() -> None:
    broker, store, _clock = _broker()
    assignment = _assignment()

    issued = await _issue(broker, assignment)
    token = issued.bearer_token.reveal()
    record = store.snapshot()[0]
    persisted = json.dumps(asdict(record), default=str, sort_keys=True)

    assert record.binding == GrantLeaseBinding.from_assignment(assignment)
    assert record.permitted_verbs == ("document.read", "ticket.read")
    assert (record.authority_evaluation_id, record.authority_evaluation_digest) == (
        AUTHORITY_EVALUATION_ID,
        AUTHORITY_EVALUATION_DIGEST,
    )
    assert record.token_digest not in {token, issued.lease.lease_id}
    assert token not in persisted
    assert token not in repr(record)
    assert token not in repr(issued)
    assert not hasattr(issued.bearer_token, "__dict__")
    with pytest.raises(TypeError, match="cannot be serialized"):
        pickle.dumps(issued)


@pytest.mark.parametrize(
    "foreign",
    [
        _assignment(tenant="tenant-2"),
        _assignment(workspace="workspace-2"),
        _assignment(root="root-2"),
        _assignment(phase="phase-2"),
        _assignment(assignment="assignment-2"),
    ],
)
async def test_authentication_is_bound_to_every_scope_component(
    foreign: PhaseAssignmentRef,
) -> None:
    broker, _store, _clock = _broker()
    expected = _assignment()
    issued = await _issue(broker, expected)

    with pytest.raises(GrantAuthenticationRejected, match="rejected"):
        await broker.authenticate(
            issued.bearer_token,
            foreign,
            verb_id="ticket.read",
            policy_generation=1,
        )
    assert await broker.authenticate(
        issued.bearer_token,
        expected,
        verb_id="ticket.read",
        policy_generation=1,
    )


async def test_only_supplied_concrete_authority_snapshot_can_authorize() -> None:
    broker, _store, _clock = _broker()
    assignment = _assignment()
    issued = await _issue(broker, assignment)

    for verb, generation, bearer in (
        ("ticket.write", 1, issued.bearer_token),
        ("ticket.read", 2, issued.bearer_token),
        ("ticket.read", 1, EphemeralBearer("unrelated-secret")),
    ):
        with pytest.raises(GrantAuthenticationRejected, match="rejected"):
            await broker.authenticate(
                bearer, assignment, verb_id=verb, policy_generation=generation
            )
    with pytest.raises(ValueError, match="concrete"):
        await broker.issue(
            assignment,
            expires_at=NOW + timedelta(seconds=60),
            policy_generation=2,
            permitted_verbs=("*",),
            authority_evaluation_id=AUTHORITY_EVALUATION_ID,
            authority_evaluation_digest=AUTHORITY_EVALUATION_DIGEST,
        )
    with pytest.raises(ValueError, match="at most"):
        await broker.issue(
            assignment,
            expires_at=NOW + timedelta(seconds=60),
            policy_generation=2,
            permitted_verbs=tuple(f"tool.verb{index}" for index in range(257)),
            authority_evaluation_id=AUTHORITY_EVALUATION_ID,
            authority_evaluation_digest=AUTHORITY_EVALUATION_DIGEST,
        )
    with pytest.raises(ValueError, match="positive integer"):
        await broker.authenticate(
            issued.bearer_token,
            assignment,
            verb_id="ticket.read",
            policy_generation=True,
        )


async def test_expiry_uses_server_clock_and_ttl_is_bounded() -> None:
    broker, store, clock = _broker(max_ttl_seconds=60)
    assignment = _assignment()
    issued = await _issue(broker, assignment)
    clock.advance(60)

    assert not await broker.is_active(
        issued.lease.lease_id,
        assignment,
        at=NOW - timedelta(days=365),
        policy_generation=1,
    )
    with pytest.raises(GrantAuthenticationRejected, match="rejected"):
        await broker.authenticate(
            issued.bearer_token,
            assignment,
            verb_id="ticket.read",
            policy_generation=1,
        )
    assert store.snapshot()[0].status is GrantLeaseStatus.EXPIRED
    with pytest.raises(ValueError, match="TTL"):
        await broker.issue(
            assignment,
            expires_at=clock.value + timedelta(seconds=61),
            policy_generation=2,
            permitted_verbs=("ticket.read",),
            authority_evaluation_id=AUTHORITY_EVALUATION_ID,
            authority_evaluation_digest=AUTHORITY_EVALUATION_DIGEST,
        )


async def test_concurrent_issue_has_one_winner_and_generation_replay_fails() -> None:
    broker, store, _clock = _broker()
    assignment = _assignment()
    attempts = await asyncio.gather(
        _issue(broker, assignment),
        _issue(broker, assignment),
        return_exceptions=True,
    )

    winners = [item for item in attempts if isinstance(item, IssuedGrant)]
    conflicts = [item for item in attempts if isinstance(item, ActiveGrantGenerationConflict)]
    assert len(winners) == len(conflicts) == 1
    first = winners[0]
    second = await _issue(broker, assignment, generation=2)
    with pytest.raises(GrantAuthenticationRejected, match="rejected"):
        await broker.authenticate(
            first.bearer_token,
            assignment,
            verb_id="ticket.read",
            policy_generation=1,
        )
    assert await broker.authenticate(
        second.bearer_token,
        assignment,
        verb_id="ticket.read",
        policy_generation=2,
    )
    with pytest.raises(StaleGrantGeneration):
        await _issue(broker, assignment, generation=1)
    assert any(
        record.revocation_reason == "superseded_generation" for record in store.snapshot()
    )


@pytest.mark.invariant("SEC-152")
async def test_exact_and_cancellation_revocation_fail_closed_immediately() -> None:
    broker, store, _clock = _broker()
    assignment = _assignment()
    issued = await _issue(broker, assignment)

    await broker.revoke_bound(
        issued.lease.lease_id,
        _assignment(assignment="foreign-assignment"),
        reason="operator_cancelled",
    )
    assert await broker.authenticate(
        issued.bearer_token,
        assignment,
        verb_id="ticket.read",
        policy_generation=1,
    )
    assert await broker.cancel_assignment(assignment) == 1
    results = await asyncio.gather(
        *(
            broker.authenticate(
                issued.bearer_token,
                assignment,
                verb_id="ticket.read",
                policy_generation=1,
            )
            for _ in range(20)
        ),
        return_exceptions=True,
    )
    assert all(isinstance(item, GrantAuthenticationRejected) for item in results)
    record = store.snapshot()[0]
    assert (record.status, record.revocation_reason) == (
        GrantLeaseStatus.REVOKED,
        "assignment_cancelled",
    )
    with pytest.raises(StaleGrantGeneration):
        await _issue(broker, assignment, generation=1)


async def test_operator_revoke_requires_exact_assignment_scope() -> None:
    broker, _store, _clock = _broker()
    assignment = _assignment()
    issued = await _issue(broker, assignment)

    await broker.revoke(
        issued.lease.lease_id,
        _assignment(tenant="tenant-foreign"),
        reason="operator_cancelled",
    )
    assert await broker.authenticate(
        issued.bearer_token,
        assignment,
        verb_id="ticket.read",
        policy_generation=1,
    )
    await broker.revoke(
        issued.lease.lease_id, assignment, reason="operator_cancelled"
    )
    with pytest.raises(GrantAuthenticationRejected, match="rejected"):
        await broker.authenticate(
            issued.bearer_token,
            assignment,
            verb_id="ticket.read",
            policy_generation=1,
        )


@pytest.mark.parametrize(
    "reason",
    ("x" * 161, "invalid\nreason", "invalid\x7freason", "invalid\x85reason", "\ud800"),
)
async def test_revocation_reason_matches_bounded_utf8_storage_policy(reason: str) -> None:
    broker, _store, _clock = _broker()
    assignment = _assignment()
    issued = await _issue(broker, assignment)

    with pytest.raises(ValueError, match="reason|UTF-8"):
        await broker.revoke(issued.lease.lease_id, assignment, reason=reason)
    assert await broker.authenticate(
        issued.bearer_token,
        assignment,
        verb_id="ticket.read",
        policy_generation=1,
    )


async def test_root_revocation_is_exactly_tenant_workspace_and_root_scoped() -> None:
    broker, _store, _clock = _broker()
    first_assignment = _assignment(assignment="assignment-1")
    sibling_assignment = _assignment(phase="phase-2", assignment="assignment-2")
    other_root_assignment = _assignment(root="root-2", assignment="assignment-3")
    other_workspace_assignment = _assignment(
        workspace="workspace-2", assignment="assignment-4"
    )
    first = await _issue(broker, first_assignment)
    sibling = await _issue(broker, sibling_assignment)
    other = await _issue(broker, other_root_assignment)
    other_workspace = await _issue(broker, other_workspace_assignment)

    assert await broker.cancel_root("tenant-1", "workspace-1", "root-1") == 2
    for issued, assignment in ((first, first_assignment), (sibling, sibling_assignment)):
        with pytest.raises(GrantAuthenticationRejected, match="rejected"):
            await broker.authenticate(
                issued.bearer_token,
                assignment,
                verb_id="ticket.read",
                policy_generation=1,
            )
    assert await broker.authenticate(
        other.bearer_token,
        other_root_assignment,
        verb_id="ticket.read",
        policy_generation=1,
    )
    assert await broker.authenticate(
        other_workspace.bearer_token,
        other_workspace_assignment,
        verb_id="ticket.read",
        policy_generation=1,
    )
