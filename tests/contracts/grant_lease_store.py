"""Reusable behavioral contract for every GrantLeaseStore adapter."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from boltrig.fleet.domain.grant_lease import (
    GrantAuthoritySnapshot,
    GrantLeaseCandidate,
    GrantLeaseBinding,
    GrantLeaseConflict,
    GrantLeaseStatus,
    GrantRootBinding,
    StaleGrantGeneration,
    StoredGrantLease,
)
from boltrig.fleet.ports.grant_leases import GrantLeaseStore
from tests.contracts.grant_lease_fixtures import (
    NOW,
    attempt_insert,
    authority_snapshot,
    binding,
    foreign_bindings,
    lease,
)

AuthorityInstaller = Callable[[GrantAuthoritySnapshot, datetime], Awaitable[None]]


class GrantLeaseStoreContract:
    """Mixin collected only through a concrete Test* adapter subclass."""

    @pytest.fixture
    def grant_store(self) -> GrantLeaseStore:
        raise NotImplementedError

    @pytest.fixture
    def grant_authority_installer(self) -> AuthorityInstaller:
        raise NotImplementedError

    @staticmethod
    async def _authorize(
        installer: AuthorityInstaller,
        *records: GrantLeaseCandidate,
        now: datetime = NOW,
    ) -> None:
        installed: set[GrantAuthoritySnapshot] = set()
        for value in records:
            snapshot = value.authority_snapshot
            if snapshot not in installed:
                await installer(snapshot, now)
                installed.add(snapshot)

    async def test_exact_digest_id_scope_and_authority_lookup(
        self,
        grant_store: GrantLeaseStore,
        grant_authority_installer: AuthorityInstaller,
    ) -> None:
        candidate = lease("lease-exact")
        await self._authorize(grant_authority_installer, candidate)
        expected = await grant_store.insert_active(
            candidate,
            expected_authority=candidate.authority_snapshot,
            now=NOW,
        )

        assert expected.lease_generation == 1
        assert await grant_store.get_by_id(expected.lease_id, expected.binding) == expected
        assert (
            await grant_store.get_by_id(expected.lease_id, binding(tenant="tenant-foreign")) is None
        )
        assert (
            await grant_store.find_active_by_digest(
                expected.token_digest,
                expected.binding,
                now=NOW,
                expected_authority=candidate.authority_snapshot,
            )
            == expected
        )
        assert (
            await grant_store.find_active_by_id(
                expected.lease_id,
                expected.binding,
                now=NOW,
                expected_authority=candidate.authority_snapshot,
            )
            == expected
        )
        for foreign in foreign_bindings():
            assert (
                await grant_store.find_active_by_digest(
                    expected.token_digest,
                    foreign,
                    now=NOW,
                    expected_authority=candidate.authority_snapshot,
                )
                is None
            )
        wrong_authority = authority_snapshot(
            scope=candidate.binding,
            authority_policy_generation=2,
        )
        assert (
            await grant_store.find_active_by_digest(
                expected.token_digest,
                expected.binding,
                now=NOW,
                expected_authority=wrong_authority,
            )
            is None
        )
        assert (
            await grant_store.find_active_by_digest(
                "not-a-digest",
                expected.binding,
                now=NOW,
                expected_authority=candidate.authority_snapshot,
            )
            is None
        )

    async def test_identifier_and_digest_collisions_are_atomic(
        self,
        grant_store: GrantLeaseStore,
        grant_authority_installer: AuthorityInstaller,
    ) -> None:
        original = lease("lease-original")
        duplicate_id = lease(
            original.lease_id,
            scope=binding(assignment="assignment-2"),
            issue_operation_id="issue-duplicate-id",
            token_name="different-bearer",
        )
        duplicate_digest = lease(
            "lease-digest-copy",
            scope=binding(assignment="assignment-3"),
            token_name="bearer-lease-original",
        )
        await self._authorize(
            grant_authority_installer,
            original,
            duplicate_id,
            duplicate_digest,
        )
        stored = await grant_store.insert_active(
            original,
            expected_authority=original.authority_snapshot,
            now=NOW,
        )

        for collision in (duplicate_id, duplicate_digest):
            with pytest.raises(GrantLeaseConflict, match="already inserted") as caught:
                await grant_store.insert_active(
                    collision,
                    expected_authority=collision.authority_snapshot,
                    now=NOW,
                )
            assert collision.token_digest not in str(caught.value)
            assert collision.lease_id not in str(caught.value)
        assert await grant_store.get_by_id(stored.lease_id, stored.binding) == stored

    async def test_concurrent_initial_issue_has_exactly_one_winner(
        self,
        grant_store: GrantLeaseStore,
        grant_authority_installer: AuthorityInstaller,
    ) -> None:
        first = lease("lease-race-a")
        second = lease("lease-race-b")
        await self._authorize(grant_authority_installer, first)

        attempts = await asyncio.gather(
            attempt_insert(grant_store, first),
            attempt_insert(grant_store, second),
        )

        winners = [item for item in attempts if isinstance(item, StoredGrantLease)]
        losers = [item for item in attempts if isinstance(item, StaleGrantGeneration)]
        assert len(winners) == len(losers) == 1
        assert winners[0].lease_generation == 1

    async def test_concurrent_explicit_replacements_have_one_cas_winner(
        self,
        grant_store: GrantLeaseStore,
        grant_authority_installer: AuthorityInstaller,
    ) -> None:
        original = lease("lease-replace-original")
        await self._authorize(grant_authority_installer, original)
        first = await grant_store.insert_active(
            original,
            expected_authority=original.authority_snapshot,
            now=NOW,
        )
        replacement_a = lease(
            "lease-replace-a",
            expected_current_lease_generation=first.lease_generation,
        )
        replacement_b = lease(
            "lease-replace-b",
            expected_current_lease_generation=first.lease_generation,
        )

        attempts = await asyncio.gather(
            attempt_insert(grant_store, replacement_a),
            attempt_insert(grant_store, replacement_b),
        )

        winners = [item for item in attempts if isinstance(item, StoredGrantLease)]
        losers = [item for item in attempts if isinstance(item, StaleGrantGeneration)]
        assert len(winners) == len(losers) == 1
        assert winners[0].lease_generation == 2
        stored_first = await grant_store.get_by_id(first.lease_id, first.binding)
        assert stored_first is not None
        assert stored_first.revocation_reason == "superseded_generation"

    async def test_issue_operation_is_idempotent_and_payload_bound(
        self,
        grant_store: GrantLeaseStore,
        grant_authority_installer: AuthorityInstaller,
    ) -> None:
        candidate = lease("lease-idempotent", issue_operation_id="issue-stable")
        await self._authorize(grant_authority_installer, candidate)
        first = await grant_store.insert_active(
            candidate,
            expected_authority=candidate.authority_snapshot,
            now=NOW,
        )
        replay = await grant_store.insert_active(
            candidate,
            expected_authority=candidate.authority_snapshot,
            now=NOW,
        )

        assert replay == first
        assert (
            await grant_store.get_by_issue_operation_id(
                candidate.issue_operation_id,
                candidate.binding,
            )
            == first
        )
        changed = replace(candidate, lease_id="lease-idempotent-changed")
        with pytest.raises(GrantLeaseConflict, match="operation conflicts"):
            await grant_store.insert_active(
                changed,
                expected_authority=changed.authority_snapshot,
                now=NOW,
            )
        replacement = lease(
            "lease-after-operation-conflict",
            expected_current_lease_generation=1,
        )
        stored_replacement = await grant_store.insert_active(
            replacement,
            expected_authority=replacement.authority_snapshot,
            now=NOW,
        )
        assert stored_replacement.lease_generation == 2

    async def test_generation_fence_survives_assignment_and_root_revocation(
        self,
        grant_store: GrantLeaseStore,
        grant_authority_installer: AuthorityInstaller,
    ) -> None:
        first = lease("lease-generation-1")
        await self._authorize(grant_authority_installer, first)
        await grant_store.insert_active(
            first,
            expected_authority=first.authority_snapshot,
            now=NOW,
        )
        assert (
            await grant_store.revoke_assignment(
                first.binding,
                now=NOW,
                reason="assignment_cancelled",
            )
            == 1
        )
        with pytest.raises(StaleGrantGeneration):
            await grant_store.insert_active(
                lease("lease-after-assignment-cancel"),
                expected_authority=first.authority_snapshot,
                now=NOW,
            )

        root_target = lease(
            "lease-root-generation-1",
            scope=binding(phase="phase-2", assignment="assignment-2"),
        )
        await self._authorize(grant_authority_installer, root_target)
        await grant_store.insert_active(
            root_target,
            expected_authority=root_target.authority_snapshot,
            now=NOW,
        )
        root = GrantRootBinding("tenant-1", "workspace-1", "root-1")
        assert (
            await grant_store.revoke_root(
                root,
                now=NOW,
                reason="root_run_cancelled",
            )
            == 1
        )
        with pytest.raises(StaleGrantGeneration):
            await grant_store.insert_active(
                lease(
                    "lease-root-new-assignment",
                    scope=binding(phase="phase-3", assignment="assignment-3"),
                ),
                expected_authority=root_target.authority_snapshot,
                now=NOW,
            )

    async def test_cancel_and_explicit_reissue_race_fails_closed(
        self,
        grant_store: GrantLeaseStore,
        grant_authority_installer: AuthorityInstaller,
    ) -> None:
        original = lease("lease-cancel-race")
        await self._authorize(grant_authority_installer, original)
        stored = await grant_store.insert_active(
            original,
            expected_authority=original.authority_snapshot,
            now=NOW,
        )
        replacement = lease(
            "lease-cancel-race-next",
            expected_current_lease_generation=stored.lease_generation,
        )

        issued, revoked = await asyncio.gather(
            attempt_insert(grant_store, replacement),
            grant_store.revoke_assignment(
                original.binding,
                now=NOW,
                reason="assignment_cancelled",
            ),
        )

        assert isinstance(issued, (StoredGrantLease, StaleGrantGeneration))
        assert revoked == 1
        assert (
            await grant_store.find_active_by_digest(
                replacement.token_digest,
                replacement.binding,
                now=NOW,
                expected_authority=replacement.authority_snapshot,
            )
            is None
        )

    async def test_same_authority_reissue_advances_only_lease_generation(
        self,
        grant_store: GrantLeaseStore,
        grant_authority_installer: AuthorityInstaller,
    ) -> None:
        original = lease("lease-same-authority")
        await self._authorize(grant_authority_installer, original)
        first = await grant_store.insert_active(
            original,
            expected_authority=original.authority_snapshot,
            now=NOW,
        )
        assert await grant_store.revoke_exact(
            first.lease_id,
            first.binding,
            now=NOW,
            reason="operator_cancelled",
        )
        replacement = lease(
            "lease-same-authority-next",
            expected_current_lease_generation=first.lease_generation,
        )
        second = await grant_store.insert_active(
            replacement,
            expected_authority=replacement.authority_snapshot,
            now=NOW,
        )

        assert (first.lease_generation, second.lease_generation) == (1, 2)
        assert (
            first.authority_policy_generation,
            second.authority_policy_generation,
        ) == (1, 1)

    @pytest.mark.parametrize(
        "authority_change",
        (
            {"authority_evaluation_id": "authority-forged"},
            {"authority_evaluation_digest": "sha256:" + "b" * 64},
            {"authority_policy_generation": 2},
            {"permitted_verbs": ("document.read", "ticket.read", "ticket.write")},
        ),
    )
    async def test_candidate_cannot_alter_current_authority_or_consume_fence(
        self,
        grant_store: GrantLeaseStore,
        grant_authority_installer: AuthorityInstaller,
        authority_change: dict[str, object],
    ) -> None:
        original = lease("lease-authority-original")
        await self._authorize(grant_authority_installer, original)
        first = await grant_store.insert_active(
            original,
            expected_authority=original.authority_snapshot,
            now=NOW,
        )
        forged_authority = authority_snapshot(
            scope=original.binding,
            **authority_change,
        )
        forged = lease(
            "lease-authority-forged",
            authority=forged_authority,
            expected_current_lease_generation=first.lease_generation,
        )
        with pytest.raises(GrantLeaseConflict, match="authority differs"):
            await grant_store.insert_active(
                forged,
                expected_authority=original.authority_snapshot,
                now=NOW,
            )
        valid = lease(
            "lease-authority-valid",
            expected_current_lease_generation=first.lease_generation,
        )
        second = await grant_store.insert_active(
            valid,
            expected_authority=original.authority_snapshot,
            now=NOW,
        )
        assert second.lease_generation == 2

    async def test_policy_rollover_immediately_invalidates_old_authority(
        self,
        grant_store: GrantLeaseStore,
        grant_authority_installer: AuthorityInstaller,
    ) -> None:
        original = lease("lease-policy-old")
        await self._authorize(grant_authority_installer, original)
        first = await grant_store.insert_active(
            original,
            expected_authority=original.authority_snapshot,
            now=NOW,
        )
        replacement_authority = authority_snapshot(
            scope=original.binding,
            authority_policy_generation=2,
            authority_evaluation_id="authority-2",
            authority_evaluation_digest="sha256:" + "b" * 64,
            permitted_verbs=("document.read",),
        )
        replacement = lease(
            "lease-policy-new",
            authority=replacement_authority,
            expected_current_lease_generation=first.lease_generation,
        )
        await grant_authority_installer(replacement.authority_snapshot, NOW)

        assert (
            await grant_store.find_active_by_digest(
                first.token_digest,
                first.binding,
                now=NOW,
                expected_authority=replacement.authority_snapshot,
            )
            is None
        )
        second = await grant_store.insert_active(
            replacement,
            expected_authority=replacement.authority_snapshot,
            now=NOW,
        )
        assert (second.authority_policy_generation, second.lease_generation) == (2, 2)

    async def test_expiry_retains_fence_and_terminal_operation_receipt(
        self,
        grant_store: GrantLeaseStore,
        grant_authority_installer: AuthorityInstaller,
    ) -> None:
        original = lease("lease-expiry")
        await self._authorize(grant_authority_installer, original)
        first = await grant_store.insert_active(
            original,
            expected_authority=original.authority_snapshot,
            now=NOW,
        )
        expiry = original.expires_at
        assert (
            await grant_store.find_active_by_digest(
                original.token_digest,
                original.binding,
                now=expiry,
                expected_authority=original.authority_snapshot,
            )
            is None
        )
        replay = await grant_store.insert_active(
            original,
            expected_authority=original.authority_snapshot,
            now=expiry,
        )
        assert replay.status is GrantLeaseStatus.EXPIRED
        replacement = lease(
            "lease-after-expiry",
            issued_at=expiry,
            expected_current_lease_generation=first.lease_generation,
        )
        second = await grant_store.insert_active(
            replacement,
            expected_authority=replacement.authority_snapshot,
            now=expiry,
        )
        assert second.lease_generation == 2

    async def test_insertion_rejects_future_and_expired_candidates(
        self,
        grant_store: GrantLeaseStore,
        grant_authority_installer: AuthorityInstaller,
    ) -> None:
        for invalid, current in (
            (lease("lease-future", issued_at=NOW + timedelta(seconds=1)), NOW),
            (lease("lease-expired"), NOW + timedelta(seconds=60)),
        ):
            await self._authorize(grant_authority_installer, invalid, now=current)
            with pytest.raises(GrantLeaseConflict, match="not active"):
                await grant_store.insert_active(
                    invalid,
                    expected_authority=invalid.authority_snapshot,
                    now=current,
                )
            assert await grant_store.get_by_id(invalid.lease_id, invalid.binding) is None

    async def test_assignment_and_root_revoke_only_exact_scope(
        self,
        grant_store: GrantLeaseStore,
        grant_authority_installer: AuthorityInstaller,
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
        await self._authorize(grant_authority_installer, exact, sibling, *foreign)
        stored = []
        for candidate in (exact, sibling, *foreign):
            stored.append(
                await grant_store.insert_active(
                    candidate,
                    expected_authority=candidate.authority_snapshot,
                    now=NOW,
                )
            )

        wrong = binding(assignment="wrong-assignment")
        assert not await grant_store.revoke_exact(
            stored[0].lease_id,
            wrong,
            now=NOW,
            reason="wrong_scope",
        )
        assert (
            await grant_store.revoke_assignment(
                exact.binding,
                now=NOW,
                reason="assignment_cancelled",
            )
            == 1
        )
        root = GrantRootBinding("tenant-1", "workspace-1", "root-1")
        assert (
            await grant_store.revoke_root(
                root,
                now=NOW,
                reason="root_run_cancelled",
            )
            == 1
        )
        for record in stored[:2]:
            assert await grant_store.get_by_id(record.lease_id, record.binding) is not None
            assert (
                await grant_store.find_active_by_id(
                    record.lease_id,
                    record.binding,
                    now=NOW,
                    expected_authority=record.authority_snapshot,
                )
                is None
            )
        for record in stored[2:]:
            assert (
                await grant_store.find_active_by_id(
                    record.lease_id,
                    record.binding,
                    now=NOW,
                    expected_authority=record.authority_snapshot,
                )
                == record
            )

    async def test_invalid_reason_cannot_partially_expire_or_revoke(
        self,
        grant_store: GrantLeaseStore,
        grant_authority_installer: AuthorityInstaller,
    ) -> None:
        candidate = lease("lease-invalid-reason")
        await self._authorize(grant_authority_installer, candidate)
        stored = await grant_store.insert_active(
            candidate,
            expected_authority=candidate.authority_snapshot,
            now=NOW,
        )

        with pytest.raises(ValueError, match="control-free"):
            await grant_store.revoke_assignment(
                candidate.binding,
                now=candidate.expires_at,
                reason="invalid\nreason",
            )
        assert await grant_store.get_by_id(stored.lease_id, stored.binding) == stored

    def test_nested_binding_must_be_exact_domain_type(self) -> None:
        class DerivedBinding(GrantLeaseBinding):
            pass

        with pytest.raises(TypeError, match="exact GrantLeaseBinding"):
            replace(
                lease("lease-derived-binding"),
                binding=DerivedBinding(
                    "tenant-1",
                    "workspace-1",
                    "root-1",
                    "phase-1",
                    "assignment-1",
                ),
            )


__all__ = ["AuthorityInstaller", "GrantLeaseStoreContract"]
