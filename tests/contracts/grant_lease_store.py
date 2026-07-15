"""Reusable behavioral contract for every GrantLeaseStore adapter."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest

from boltrig.fleet.domain.grant_lease import (
    ActiveGrantGenerationConflict,
    GrantLeaseBinding,
    GrantLeaseConflict,
    GrantLeaseStatus,
    GrantRootBinding,
    StaleGrantGeneration,
)
from boltrig.fleet.ports.grant_leases import GrantLeaseStore
from tests.contracts.grant_lease_fixtures import (
    NOW,
    attempt_insert,
    binding,
    foreign_bindings,
    lease,
)


class GrantLeaseStoreContract:
    """Mixin collected only through a concrete Test* adapter subclass."""

    @pytest.fixture
    def grant_store(self) -> GrantLeaseStore:
        raise NotImplementedError

    async def test_exact_digest_id_scope_and_generation_lookup(
        self, grant_store: GrantLeaseStore
    ) -> None:
        expected = lease("lease-exact")
        await grant_store.insert_active(expected, now=NOW)

        assert await grant_store.get_by_id(expected.lease_id, expected.binding) == expected
        assert await grant_store.get_by_id(
            expected.lease_id, binding(tenant="tenant-foreign")
        ) is None
        assert await grant_store.find_active_by_digest(
            expected.token_digest, expected.binding, now=NOW, policy_generation=1
        ) == expected
        assert await grant_store.find_active_by_id(
            expected.lease_id, expected.binding, now=NOW, policy_generation=1
        ) == expected
        for foreign in foreign_bindings():
            assert await grant_store.find_active_by_digest(
                expected.token_digest, foreign, now=NOW, policy_generation=1
            ) is None
            assert await grant_store.find_active_by_id(
                expected.lease_id, foreign, now=NOW, policy_generation=1
            ) is None
        assert await grant_store.find_active_by_digest(
            "b" * 64,
            expected.binding,
            now=NOW,
            policy_generation=1,
        ) is None
        assert await grant_store.find_active_by_digest(
            expected.token_digest, expected.binding, now=NOW, policy_generation=2
        ) is None
        assert await grant_store.find_active_by_digest(
            "\N{SNOWMAN}", expected.binding, now=NOW, policy_generation=1
        ) is None

    async def test_identifier_and_digest_collisions_are_atomic(
        self, grant_store: GrantLeaseStore
    ) -> None:
        original = lease("lease-original")
        await grant_store.insert_active(original, now=NOW)
        duplicate_id = lease(
            original.lease_id,
            scope=binding(assignment="assignment-2"),
            token_name="different-bearer",
        )
        duplicate_digest = lease(
            "lease-digest-copy",
            scope=binding(assignment="assignment-3"),
            token_name="bearer-lease-original",
        )

        for collision in (duplicate_id, duplicate_digest):
            with pytest.raises(GrantLeaseConflict, match="already inserted") as caught:
                await grant_store.insert_active(collision, now=NOW)
            assert collision.token_digest not in str(caught.value)
            assert collision.lease_id not in str(caught.value)
        assert await grant_store.find_active_by_id(
            original.lease_id, original.binding, now=NOW, policy_generation=1
        ) == original

    async def test_concurrent_same_generation_has_exactly_one_winner(
        self, grant_store: GrantLeaseStore
    ) -> None:
        attempts = await asyncio.gather(
            attempt_insert(grant_store, lease("lease-race-a")),
            attempt_insert(grant_store, lease("lease-race-b")),
        )

        assert sum(item is None for item in attempts) == 1
        assert sum(isinstance(item, ActiveGrantGenerationConflict) for item in attempts) == 1

    async def test_generation_fence_survives_assignment_and_root_revocation(
        self, grant_store: GrantLeaseStore
    ) -> None:
        first = lease("lease-generation-1")
        await grant_store.insert_active(first, now=NOW)
        assert await grant_store.revoke_assignment(
            first.binding, now=NOW, reason="assignment_cancelled"
        ) == 1
        with pytest.raises(StaleGrantGeneration):
            await grant_store.insert_active(
                lease("lease-generation-1-replay"), now=NOW
            )
        with pytest.raises(StaleGrantGeneration):
            await grant_store.insert_active(
                lease("lease-generation-2", generation=2), now=NOW
            )

        root_target = lease(
            "lease-root-generation-1",
            scope=binding(phase="phase-2", assignment="assignment-2"),
        )
        await grant_store.insert_active(root_target, now=NOW)
        root = GrantRootBinding("tenant-1", "workspace-1", "root-1")
        assert await grant_store.revoke_root(
            root, now=NOW, reason="root_run_cancelled"
        ) == 1
        with pytest.raises(StaleGrantGeneration):
            await grant_store.insert_active(
                lease(
                    "lease-root-generation-2",
                    scope=root_target.binding,
                    generation=2,
                ),
                now=NOW,
            )
        with pytest.raises(StaleGrantGeneration):
            await grant_store.insert_active(
                lease(
                    "lease-root-new-assignment",
                    scope=binding(phase="phase-3", assignment="assignment-3"),
                ),
                now=NOW,
            )

    async def test_cancel_and_higher_generation_issue_race_fails_closed(
        self, grant_store: GrantLeaseStore
    ) -> None:
        original = lease("lease-cancel-race")
        replacement = lease("lease-cancel-race-next", generation=2)
        await grant_store.insert_active(original, now=NOW)

        issued, revoked = await asyncio.gather(
            attempt_insert(grant_store, replacement),
            grant_store.revoke_assignment(
                original.binding, now=NOW, reason="assignment_cancelled"
            ),
        )

        assert issued is None or isinstance(issued, StaleGrantGeneration)
        assert revoked == 1
        assert await grant_store.find_active_by_digest(
            replacement.token_digest,
            replacement.binding,
            now=NOW,
            policy_generation=2,
        ) is None
        with pytest.raises(StaleGrantGeneration):
            await grant_store.insert_active(
                lease("lease-cancel-race-later", generation=3), now=NOW
            )

    async def test_higher_generation_atomically_supersedes_active_lease(
        self, grant_store: GrantLeaseStore
    ) -> None:
        first = lease("lease-superseded")
        second = lease("lease-current", generation=2)
        await grant_store.insert_active(first, now=NOW)
        await grant_store.insert_active(second, now=NOW)

        stored_first = await grant_store.get_by_id(first.lease_id, first.binding)
        assert stored_first is not None
        assert (stored_first.status, stored_first.revocation_reason) == (
            GrantLeaseStatus.REVOKED,
            "superseded_generation",
        )
        assert await grant_store.find_active_by_digest(
            first.token_digest, first.binding, now=NOW, policy_generation=1
        ) is None
        assert await grant_store.find_active_by_digest(
            second.token_digest, second.binding, now=NOW, policy_generation=2
        ) == second

    async def test_expiry_is_fail_closed_and_retains_generation_fence(
        self, grant_store: GrantLeaseStore
    ) -> None:
        original = lease("lease-expiry")
        await grant_store.insert_active(original, now=NOW)
        expiry = original.expires_at

        assert await grant_store.find_active_by_digest(
            original.token_digest,
            original.binding,
            now=expiry,
            policy_generation=1,
        ) is None
        stored = await grant_store.get_by_id(original.lease_id, original.binding)
        assert stored is not None and stored.status is GrantLeaseStatus.EXPIRED
        with pytest.raises(StaleGrantGeneration):
            await grant_store.insert_active(
                lease("lease-expiry-replay", issued_at=expiry), now=expiry
            )
        await grant_store.insert_active(
            lease("lease-after-expiry", generation=2, issued_at=expiry), now=expiry
        )

    async def test_insertion_rejects_future_and_expired_records(
        self, grant_store: GrantLeaseStore
    ) -> None:
        for invalid, current in (
            (lease("lease-future", issued_at=NOW + timedelta(seconds=1)), NOW),
            (lease("lease-expired"), NOW + timedelta(seconds=60)),
        ):
            with pytest.raises(GrantLeaseConflict, match="not active"):
                await grant_store.insert_active(invalid, now=current)
            assert await grant_store.get_by_id(invalid.lease_id, invalid.binding) is None

    async def test_assignment_and_root_revoke_only_exact_scope(
        self, grant_store: GrantLeaseStore
    ) -> None:
        exact = lease("lease-root-exact")
        sibling = lease(
            "lease-root-sibling",
            scope=binding(phase="phase-2", assignment="assignment-2"),
        )
        foreign = (
            lease("lease-other-root", scope=binding(root="root-2")),
            lease("lease-other-workspace", scope=binding(workspace="workspace-2")),
            lease("lease-other-tenant", scope=binding(tenant="tenant-2")),
        )
        for record in (exact, sibling, *foreign):
            await grant_store.insert_active(record, now=NOW)

        wrong = binding(assignment="wrong-assignment")
        assert not await grant_store.revoke_exact(
            exact.lease_id, wrong, now=NOW, reason="wrong_scope"
        )
        assert await grant_store.revoke_assignment(
            exact.binding, now=NOW, reason="assignment_cancelled"
        ) == 1
        assert await grant_store.find_active_by_id(
            sibling.lease_id, sibling.binding, now=NOW, policy_generation=1
        ) == sibling
        root = GrantRootBinding("tenant-1", "workspace-1", "root-1")
        assert await grant_store.revoke_root(
            root, now=NOW, reason="root_run_cancelled"
        ) == 1
        for record in (exact, sibling):
            assert await grant_store.find_active_by_id(
                record.lease_id, record.binding, now=NOW, policy_generation=1
            ) is None
        for record in foreign:
            assert await grant_store.find_active_by_id(
                record.lease_id, record.binding, now=NOW, policy_generation=1
            ) == record

    async def test_successful_exact_revoke_is_scoped_persisted_and_idempotent(
        self, grant_store: GrantLeaseStore
    ) -> None:
        original = lease("lease-exact-revoke")
        await grant_store.insert_active(original, now=NOW)
        foreign = binding(assignment="assignment-foreign")

        assert not await grant_store.revoke_exact(
            original.lease_id, foreign, now=NOW, reason="operator_cancelled"
        )
        assert await grant_store.revoke_exact(
            original.lease_id,
            original.binding,
            now=NOW,
            reason="operator_cancelled",
        )
        assert not await grant_store.revoke_exact(
            original.lease_id,
            original.binding,
            now=NOW,
            reason="operator_cancelled",
        )
        stored = await grant_store.get_by_id(original.lease_id, original.binding)
        assert stored is not None
        assert (stored.status, stored.revoked_at, stored.revocation_reason) == (
            GrantLeaseStatus.REVOKED,
            NOW,
            "operator_cancelled",
        )
        assert await grant_store.get_by_id(original.lease_id, foreign) is None
        assert await grant_store.find_active_by_digest(
            original.token_digest,
            original.binding,
            now=NOW,
            policy_generation=1,
        ) is None

    async def test_root_revoke_is_atomic_under_clock_rollback(
        self, grant_store: GrantLeaseStore
    ) -> None:
        first = lease("lease-clock-first")
        later_time = NOW + timedelta(seconds=10)
        second = lease(
            "lease-clock-second",
            scope=binding(phase="phase-2", assignment="assignment-2"),
            issued_at=later_time,
        )
        await grant_store.insert_active(first, now=NOW)
        await grant_store.insert_active(second, now=later_time)

        root = GrantRootBinding("tenant-1", "workspace-1", "root-1")
        rolled_back = NOW + timedelta(seconds=5)
        assert await grant_store.revoke_root(
            root, now=rolled_back, reason="root_run_cancelled"
        ) == 2
        first_stored = await grant_store.get_by_id(first.lease_id, first.binding)
        second_stored = await grant_store.get_by_id(second.lease_id, second.binding)
        assert first_stored is not None and second_stored is not None
        assert first_stored.revoked_at == rolled_back
        assert second_stored.revoked_at == later_time
        assert first_stored.status is second_stored.status is GrantLeaseStatus.REVOKED

    async def test_invalid_reason_cannot_partially_expire_or_revoke(
        self, grant_store: GrantLeaseStore
    ) -> None:
        original = lease("lease-invalid-reason")
        await grant_store.insert_active(original, now=NOW)

        with pytest.raises(ValueError, match="control-free"):
            await grant_store.revoke_assignment(
                original.binding,
                now=original.expires_at,
                reason="invalid\nreason",
            )
        assert await grant_store.get_by_id(
            original.lease_id, original.binding
        ) == original

    async def test_nested_binding_must_be_exact_domain_type(
        self, grant_store: GrantLeaseStore
    ) -> None:
        class DerivedBinding(GrantLeaseBinding):
            pass

        malformed = replace(
            lease("lease-derived-binding"),
            binding=DerivedBinding(
                "tenant-1", "workspace-1", "root-1", "phase-1", "assignment-1"
            ),
        )
        with pytest.raises(TypeError, match="exact GrantLeaseBinding"):
            await grant_store.insert_active(malformed, now=NOW)

    async def test_revocation_is_visible_to_all_later_concurrent_lookups(
        self, grant_store: GrantLeaseStore
    ) -> None:
        original = lease("lease-immediate-revoke")
        await grant_store.insert_active(original, now=NOW)
        assert await grant_store.revoke_assignment(
            original.binding, now=NOW, reason="assignment_cancelled"
        ) == 1
        lookups = await asyncio.gather(
            *(
                grant_store.find_active_by_digest(
                    original.token_digest,
                    original.binding,
                    now=NOW,
                    policy_generation=1,
                )
                for _ in range(32)
            )
        )
        assert lookups == [None] * 32
__all__ = ["GrantLeaseStoreContract"]
