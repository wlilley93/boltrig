"""Production in-memory adapter coverage plus reusable store contract."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from boltrig.fleet.domain.grant_lease import (
    GrantLeaseConflict,
    GrantLeaseStatus,
    GrantRootBinding,
    StaleGrantGeneration,
)
from boltrig.fleet.infrastructure.memory_grant_leases import (
    HARD_MAX_GRANT_LEASE_STATE,
    GrantLeaseStoreCapacityExceeded,
    MemoryGrantLeaseStore,
)
from boltrig.fleet.ports.grant_leases import GrantLeaseStore
from tests.contracts.grant_lease_fixtures import NOW, attempt_insert, binding, lease
from tests.contracts.grant_lease_store import (
    GrantLeaseStoreContract,
)


class TestMemoryGrantLeaseStore(GrantLeaseStoreContract):
    @pytest.fixture
    def grant_store(self) -> GrantLeaseStore:
        return MemoryGrantLeaseStore()


async def test_assignment_cancel_is_terminal_against_concurrent_reissue() -> None:
    store = MemoryGrantLeaseStore()
    original = lease("lease-concrete-assignment-race")
    replacement = lease("lease-concrete-assignment-race-next", generation=2)
    await store.insert_active(original, now=NOW)

    issued, revoked = await asyncio.gather(
        attempt_insert(store, replacement),
        store.revoke_assignment(
            original.binding, now=NOW, reason="assignment_cancelled"
        ),
    )

    assert issued is None or isinstance(issued, StaleGrantGeneration)
    assert revoked == 1
    assert await store.find_active_by_digest(
        replacement.token_digest,
        replacement.binding,
        now=NOW,
        policy_generation=2,
    ) is None
    with pytest.raises(StaleGrantGeneration):
        await store.insert_active(lease("lease-after-assignment-cancel", generation=3), now=NOW)


async def test_root_cancel_is_atomic_during_clock_rollback_and_terminal() -> None:
    store = MemoryGrantLeaseStore()
    first = lease("lease-concrete-root-first")
    later = NOW + timedelta(seconds=10)
    second = lease(
        "lease-concrete-root-second",
        scope=binding(phase="phase-2", assignment="assignment-2"),
        issued_at=later,
    )
    await store.insert_active(first, now=NOW)
    await store.insert_active(second, now=later)

    root = GrantRootBinding("tenant-1", "workspace-1", "root-1")
    assert await store.revoke_root(
        root, now=NOW + timedelta(seconds=5), reason="root_run_cancelled"
    ) == 2
    stored = (
        await store.get_by_id(first.lease_id, first.binding),
        await store.get_by_id(second.lease_id, second.binding),
    )
    assert all(item is not None and item.status is GrantLeaseStatus.REVOKED for item in stored)
    with pytest.raises(StaleGrantGeneration):
        await store.insert_active(
            lease(
                "lease-after-root-cancel",
                scope=binding(phase="phase-3", assignment="assignment-3"),
            ),
            now=later,
        )


async def test_capacity_backpressure_never_evicts_or_partially_supersedes() -> None:
    store = MemoryGrantLeaseStore(max_records=1, max_bindings=1)
    original = lease("lease-capacity-original")
    replacement = lease("lease-capacity-replacement", generation=2)
    await store.insert_active(original, now=NOW)

    with pytest.raises(GrantLeaseStoreCapacityExceeded, match="capacity") as caught:
        await store.insert_active(replacement, now=NOW)

    assert replacement.lease_id not in str(caught.value)
    assert replacement.token_digest not in str(caught.value)
    assert await store.get_by_id(original.lease_id, original.binding) == original
    assert await store.get_by_id(replacement.lease_id, replacement.binding) is None
    assert await store.find_active_by_digest(
        original.token_digest, original.binding, now=NOW, policy_generation=1
    ) == original


async def test_binding_capacity_retains_existing_security_state() -> None:
    store = MemoryGrantLeaseStore(max_records=2, max_bindings=1)
    original = lease("lease-binding-capacity")
    await store.insert_active(original, now=NOW)
    foreign = lease(
        "lease-foreign-binding",
        scope=binding(assignment="assignment-foreign"),
    )

    with pytest.raises(GrantLeaseStoreCapacityExceeded):
        await store.insert_active(foreign, now=NOW)

    assert await store.get_by_id(original.lease_id, original.binding) == original
    assert await store.get_by_id(foreign.lease_id, foreign.binding) is None


async def test_capacity_does_not_mask_generation_or_collision_conflicts() -> None:
    store = MemoryGrantLeaseStore(max_records=1, max_bindings=1)
    original = lease("lease-priority")
    await store.insert_active(original, now=NOW)
    with pytest.raises(GrantLeaseConflict, match="already inserted"):
        await store.insert_active(
            lease("lease-collision", generation=2, token_name="bearer-lease-priority"),
            now=NOW,
        )
    await store.revoke_assignment(
        original.binding, now=NOW, reason="assignment_cancelled"
    )

    with pytest.raises(StaleGrantGeneration):
        await store.insert_active(lease("lease-stale"), now=NOW)


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
    store = MemoryGrantLeaseStore()
    rendered = repr(store)

    assert "_records" not in rendered
    assert "token_digest" not in rendered
