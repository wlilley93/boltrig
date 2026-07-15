"""Production in-memory adapter coverage plus reusable store contract."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from boltrig.fleet.domain.grant_lease import (
    GrantLeaseCandidate,
    GrantLeaseConflict,
    GrantLeaseStatus,
    GrantRootBinding,
    LeaseGenerationExhausted,
    StaleGrantGeneration,
    StoredGrantLease,
)
from boltrig.fleet.infrastructure.memory_grant_leases import (
    HARD_MAX_GRANT_LEASE_STATE,
    MAX_SIGNED_BIGINT,
    GrantLeaseStoreCapacityExceeded,
    MemoryGrantLeaseStore,
)
from boltrig.fleet.ports.grant_leases import GrantLeaseStore
from tests.contracts.grant_lease_fixtures import (
    NOW,
    attempt_insert,
    authority_snapshot,
    binding,
    lease,
)
from tests.contracts.grant_lease_store import (
    AuthorityInstaller,
    GrantLeaseStoreContract,
)


async def _install_and_insert(
    store: MemoryGrantLeaseStore,
    candidate: GrantLeaseCandidate,
    *,
    now: datetime = NOW,
) -> StoredGrantLease:
    await store.install_authority_snapshot(candidate.authority_snapshot, now=now)
    return await store.insert_active(
        candidate,
        expected_authority=candidate.authority_snapshot,
        now=now,
    )


class TestMemoryGrantLeaseStore(GrantLeaseStoreContract):
    @pytest.fixture
    def grant_store(self) -> GrantLeaseStore:
        return MemoryGrantLeaseStore()

    @pytest.fixture
    def grant_authority_installer(
        self,
        grant_store: GrantLeaseStore,
    ) -> AuthorityInstaller:
        if not isinstance(grant_store, MemoryGrantLeaseStore):
            raise TypeError("memory contract requires MemoryGrantLeaseStore")

        async def install(snapshot: object, now: datetime) -> None:
            await grant_store.install_authority_snapshot(snapshot, now=now)  # type: ignore[arg-type]

        return install  # type: ignore[return-value]


async def test_assignment_cancel_is_terminal_against_concurrent_reissue() -> None:
    store = MemoryGrantLeaseStore()
    original = lease("lease-concrete-assignment-race")
    first = await _install_and_insert(store, original)
    replacement = lease(
        "lease-concrete-assignment-race-next",
        expected_current_lease_generation=first.lease_generation,
    )

    issued, revoked = await asyncio.gather(
        attempt_insert(store, replacement),
        store.revoke_assignment(
            original.binding,
            now=NOW,
            reason="assignment_cancelled",
        ),
    )

    assert isinstance(issued, (StoredGrantLease, StaleGrantGeneration))
    assert revoked == 1
    assert (
        await store.find_active_by_digest(
            replacement.token_digest,
            replacement.binding,
            now=NOW,
            expected_authority=replacement.authority_snapshot,
        )
        is None
    )
    with pytest.raises(StaleGrantGeneration):
        await store.insert_active(
            lease("lease-after-assignment-cancel"),
            expected_authority=original.authority_snapshot,
            now=NOW,
        )


async def test_root_cancel_is_atomic_during_clock_rollback_and_terminal() -> None:
    store = MemoryGrantLeaseStore()
    first = lease("lease-concrete-root-first")
    later = NOW + timedelta(seconds=10)
    second = lease(
        "lease-concrete-root-second",
        scope=binding(phase="phase-2", assignment="assignment-2"),
        issued_at=later,
    )
    first_stored = await _install_and_insert(store, first)
    second_stored = await _install_and_insert(store, second, now=later)

    root = GrantRootBinding("tenant-1", "workspace-1", "root-1")
    assert (
        await store.revoke_root(
            root,
            now=NOW + timedelta(seconds=5),
            reason="root_run_cancelled",
        )
        == 2
    )
    stored = (
        await store.get_by_id(first_stored.lease_id, first_stored.binding),
        await store.get_by_id(second_stored.lease_id, second_stored.binding),
    )
    assert all(item is not None and item.status is GrantLeaseStatus.REVOKED for item in stored)
    with pytest.raises(StaleGrantGeneration):
        await store.insert_active(
            lease(
                "lease-after-root-cancel",
                scope=binding(phase="phase-3", assignment="assignment-3"),
            ),
            expected_authority=first.authority_snapshot,
            now=later,
        )


async def test_authority_suspension_serializes_against_reissue() -> None:
    store = MemoryGrantLeaseStore()
    original = lease("lease-approval-race")
    first = await _install_and_insert(store, original)
    replacement = lease(
        "lease-approval-race-next",
        expected_current_lease_generation=first.lease_generation,
    )

    issued, revoked = await asyncio.gather(
        attempt_insert(store, replacement),
        store.suspend_grant_authority(original.binding, now=NOW),
    )

    assert isinstance(issued, (StoredGrantLease, GrantLeaseConflict))
    assert revoked == 1
    assert (
        await store.resolve_current_grant_authority(
            _assignment_ref(original),
            at=NOW,
        )
        is None
    )
    assert (
        await store.find_active_by_digest(
            replacement.token_digest,
            replacement.binding,
            now=NOW,
            expected_authority=replacement.authority_snapshot,
        )
        is None
    )


async def test_authority_suspension_retains_generation_fence_against_aba_replay() -> None:
    store = MemoryGrantLeaseStore()
    original = lease("lease-authority-aba")
    await _install_and_insert(store, original)
    assert await store.suspend_grant_authority(original.binding, now=NOW) == 1

    with pytest.raises(GrantLeaseConflict, match="advance"):
        await store.install_authority_snapshot(original.authority_snapshot, now=NOW)

    replacement = authority_snapshot(
        scope=original.binding,
        authority_evaluation_id="authority-2",
        authority_evaluation_digest="sha256:" + "b" * 64,
        authority_policy_generation=2,
    )
    await store.install_authority_snapshot(replacement, now=NOW)
    assert (
        await store.resolve_current_grant_authority(
            _assignment_ref(original),
            at=NOW,
        )
        == replacement
    )


async def test_capacity_backpressure_never_partially_supersedes() -> None:
    store = MemoryGrantLeaseStore(max_records=1, max_bindings=1)
    original = lease("lease-capacity-original")
    first = await _install_and_insert(store, original)
    replacement = lease(
        "lease-capacity-replacement",
        expected_current_lease_generation=first.lease_generation,
    )

    with pytest.raises(GrantLeaseStoreCapacityExceeded, match="capacity") as caught:
        await store.insert_active(
            replacement,
            expected_authority=replacement.authority_snapshot,
            now=NOW,
        )

    assert replacement.lease_id not in str(caught.value)
    assert replacement.token_digest not in str(caught.value)
    assert await store.get_by_id(first.lease_id, first.binding) == first
    assert await store.get_by_id(replacement.lease_id, replacement.binding) is None
    assert (
        await store.find_active_by_digest(
            first.token_digest,
            first.binding,
            now=NOW,
            expected_authority=first.authority_snapshot,
        )
        == first
    )


async def test_binding_capacity_bounds_authority_state_before_lease_insert() -> None:
    store = MemoryGrantLeaseStore(max_records=2, max_bindings=1)
    original = lease("lease-binding-capacity")
    first = await _install_and_insert(store, original)
    foreign = lease(
        "lease-foreign-binding",
        scope=binding(assignment="assignment-foreign"),
    )
    with pytest.raises(GrantLeaseStoreCapacityExceeded):
        await store.install_authority_snapshot(foreign.authority_snapshot, now=NOW)

    assert await store.get_by_id(first.lease_id, first.binding) == first
    assert await store.get_by_id(foreign.lease_id, foreign.binding) is None


async def test_capacity_does_not_mask_collision_or_cancellation() -> None:
    store = MemoryGrantLeaseStore(max_records=1, max_bindings=1)
    original = lease("lease-priority")
    first = await _install_and_insert(store, original)
    collision = lease(
        "lease-collision",
        token_name="bearer-lease-priority",
        expected_current_lease_generation=first.lease_generation,
    )
    with pytest.raises(GrantLeaseConflict, match="already inserted"):
        await store.insert_active(
            collision,
            expected_authority=collision.authority_snapshot,
            now=NOW,
        )
    await store.revoke_assignment(
        original.binding,
        now=NOW,
        reason="assignment_cancelled",
    )
    with pytest.raises(StaleGrantGeneration):
        await store.insert_active(
            lease("lease-stale"),
            expected_authority=original.authority_snapshot,
            now=NOW,
        )


async def test_signed_bigint_exhaustion_does_not_mutate_state() -> None:
    store = MemoryGrantLeaseStore()
    candidate = lease(
        "lease-exhausted",
        expected_current_lease_generation=MAX_SIGNED_BIGINT,
    )
    await store.install_authority_snapshot(candidate.authority_snapshot, now=NOW)
    store._highest_lease_generation[candidate.binding] = MAX_SIGNED_BIGINT

    with pytest.raises(LeaseGenerationExhausted, match="exhausted"):
        await store.insert_active(
            candidate,
            expected_authority=candidate.authority_snapshot,
            now=NOW,
        )

    assert await store.get_by_id(candidate.lease_id, candidate.binding) is None
    assert (
        await store.get_by_issue_operation_id(
            candidate.issue_operation_id,
            candidate.binding,
        )
        is None
    )
    assert store._highest_lease_generation[candidate.binding] == MAX_SIGNED_BIGINT


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_records", 0),
        ("max_records", True),
        ("max_records", HARD_MAX_GRANT_LEASE_STATE + 1),
        ("max_bindings", 0),
        ("max_bindings", True),
        ("max_bindings", HARD_MAX_GRANT_LEASE_STATE + 1),
    ],
)
def test_capacity_configuration_is_strictly_bounded(field: str, value: int) -> None:
    kwargs = {field: value}
    with pytest.raises(ValueError, match="between"):
        MemoryGrantLeaseStore(**kwargs)


def test_adapter_repr_has_no_retained_identifiers_or_digests() -> None:
    rendered = repr(MemoryGrantLeaseStore())

    assert "_records" not in rendered
    assert "token_digest" not in rendered


def _assignment_ref(candidate: GrantLeaseCandidate):
    from boltrig.fleet.domain.execution import PhaseAssignmentRef, PhaseRef
    from boltrig.models import OrganisationUserRef

    binding_value = candidate.binding
    return PhaseAssignmentRef(
        PhaseRef(
            binding_value.root_run_id,
            binding_value.phase_id,
            OrganisationUserRef(binding_value.tenant_id, "user-1"),
            binding_value.workspace_id,
        ),
        binding_value.assignment_id,
    )
