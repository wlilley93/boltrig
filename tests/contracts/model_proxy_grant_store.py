"""Reusable behavioral contract for every ModelProxyGrantStore adapter.

Generalized from the memory-only assertions in ``tests/unit/test_model_proxy_grants.py``
(most of that 900-line file exercises ``PhaseScopedModelProxyGrantBroker`` racing the
memory adapter's single in-process lock via subclass overrides that stall at specific
``await`` points -- those prove asyncio scheduling properties of the broker/memory pair,
not store semantics, and do not generalize to a connection-pool-backed adapter). What
DOES generalize, and is proven here directly against ``ModelProxyGrantStore`` methods
with no broker involved, is: minted lifetime/generation on insert, exact-scope digest and
id lookups (every one of the 19 cell/model/budget fields must match), grant-id/bearer/
startup-digest collision detection with redacted error messages, the generation
compare-and-swap (same-generation-active vs stale-vs-highest-ever-seen), generation
supersession on reissue, the four-level (root/phase/assignment/cell) hierarchical
cancellation tombstones and their immediate/terminal/scoped-only effect, expiry
semantics (hidden from active lookups, fence survives, ``get_by_id`` still returns the
raw row), revocation-reason validation, and the store's own input-type guards.

Every time-sensitive method accepts an optional ``now: datetime | None`` keyword absent
from the ``ModelProxyGrantStore`` protocol itself (see ``PostgresModelProxyGrantStore``'s
docstring for why): this contract always passes it explicitly for deterministic,
wall-clock-independent assertions.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from boltrig.fleet.domain.model_proxy_grant import (
    ActiveModelProxyGenerationConflict,
    ModelProxyGrantConflict,
    ModelProxyGrantDraft,
    ModelProxyGrantStatus,
    StaleModelProxyGeneration,
)
from boltrig.fleet.domain.model_proxy_scope import (
    ModelProxyAssignmentScope,
    ModelProxyBudgetBinding,
    ModelProxyCellScope,
    ModelProxyGrantBinding,
    ModelProxyModelBinding,
    ModelProxyPhaseScope,
    ModelProxyRootScope,
    TrustedModelProxyRequestObservation,
)
from boltrig.fleet.ports.model_proxy_grants import ModelProxyGrantStore

NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)
POLICY_DIGEST = "sha256:" + "a" * 64
CGROUP_DIGEST = "sha256:" + "c" * 64


def binding(
    *,
    tenant: str = "tenant-1",
    workspace: str = "workspace-1",
    root: str = "root-1",
    phase: str = "phase-1",
    assignment: str = "assignment-1",
    cell: str = "cell-1",
    pid: int = 4321,
    pid_start_ticks: int = 998_001,
    boot_id: str = "018f4d4c-1111-7222-8333-123456789abc",
    pid_namespace_inode: int = 40_200,
    cgroup_digest: str = CGROUP_DIGEST,
    model: str = "gpt-5.2-codex",
    model_digest: str = POLICY_DIGEST,
    budget: str = "budget-1",
    max_input_tokens: int = 6_000,
    max_output_tokens: int = 4_000,
    max_total_tokens: int = 8_192,
    max_cost_micros: int = 125_000,
    budget_digest: str = POLICY_DIGEST,
) -> ModelProxyGrantBinding:
    root_scope = ModelProxyRootScope(tenant, workspace, root)
    phase_scope = ModelProxyPhaseScope(root_scope, phase)
    assignment_scope = ModelProxyAssignmentScope(phase_scope, assignment)
    cell_scope = ModelProxyCellScope(
        assignment_scope,
        cell,
        pid,
        pid_start_ticks,
        boot_id,
        pid_namespace_inode,
        cgroup_digest,
    )
    return ModelProxyGrantBinding(
        cell_scope,
        ModelProxyModelBinding(model, model_digest),
        ModelProxyBudgetBinding(
            budget,
            max_input_tokens,
            max_output_tokens,
            max_total_tokens,
            max_cost_micros,
            budget_digest,
        ),
    )


def foreign_bindings() -> tuple[ModelProxyGrantBinding, ...]:
    return (
        binding(tenant="tenant-2"),
        binding(workspace="workspace-2"),
        binding(root="root-2"),
        binding(phase="phase-2"),
        binding(assignment="assignment-2"),
        binding(cell="cell-2"),
        binding(pid=4322),
        binding(pid_start_ticks=998_002),
        binding(boot_id="018f4d4c-1111-7222-8333-123456789abd"),
        binding(pid_namespace_inode=40_201),
        binding(cgroup_digest="sha256:" + "d" * 64),
        binding(model="gpt-5.3-codex"),
        binding(model_digest="sha256:" + "b" * 64),
        binding(budget="budget-2"),
        binding(max_input_tokens=5_999),
        binding(max_output_tokens=3_999),
        binding(max_total_tokens=8_191),
        binding(max_cost_micros=124_999),
        binding(budget_digest="sha256:" + "b" * 64),
    )


def draft(
    name: str,
    *,
    binding_value: ModelProxyGrantBinding | None = None,
    generation: int = 1,
    ttl_seconds: int = 60,
    bearer_name: str | None = None,
    request_name: str | None = None,
) -> ModelProxyGrantDraft:
    return ModelProxyGrantDraft(
        grant_id=f"mpg_{name}",
        binding=binding_value or binding(),
        bearer_digest=hashlib.sha256((bearer_name or f"bearer-{name}").encode()).hexdigest(),
        startup_request_digest=hashlib.sha256(
            (request_name or f"request-{name}").encode()
        ).hexdigest(),
        ttl_seconds=ttl_seconds,
        generation=generation,
    )


def observation(binding_value: ModelProxyGrantBinding) -> TrustedModelProxyRequestObservation:
    return TrustedModelProxyRequestObservation(
        binding_value.cell, binding_value.model, binding_value.budget
    )


class ModelProxyGrantStoreContract:
    """Mixin collected only through a concrete Test* adapter subclass."""

    @pytest.fixture
    def grant_store(self) -> ModelProxyGrantStore:
        raise NotImplementedError

    async def test_insert_active_mints_lifetime_and_first_generation(
        self, grant_store: ModelProxyGrantStore
    ) -> None:
        stored = await grant_store.insert_active(draft("first"), now=NOW)

        assert stored.generation == 1
        assert stored.issued_at == NOW
        assert stored.expires_at == NOW + timedelta(seconds=60)
        assert stored.status is ModelProxyGrantStatus.ACTIVE
        assert await grant_store.get_by_id(stored.grant_id, stored.binding) == stored
        assert (
            await grant_store.find_active_by_id(
                stored.grant_id, stored.binding, generation=1, now=NOW
            )
            == stored
        )

    @pytest.mark.parametrize("foreign", foreign_bindings())
    async def test_internal_lookup_requires_every_trusted_peer_model_and_budget_field(
        self, grant_store: ModelProxyGrantStore, foreign: ModelProxyGrantBinding
    ) -> None:
        stored = await grant_store.insert_active(draft("scope-exact"), now=NOW)
        digest = stored.bearer_digest

        assert (
            await grant_store.find_active_for_trusted_observation(
                digest, observation(foreign), generation=1, now=NOW
            )
            is None
        )
        assert (
            await grant_store.find_active_for_trusted_observation(
                digest, observation(binding()), generation=2, now=NOW
            )
            is None
        )
        assert (
            await grant_store.find_active_for_trusted_observation(
                digest, observation(binding()), generation=1, now=NOW
            )
            == stored
        )

    async def test_find_active_by_id_requires_exact_binding_and_generation(
        self, grant_store: ModelProxyGrantStore
    ) -> None:
        stored = await grant_store.insert_active(draft("by-id"), now=NOW)

        assert (
            await grant_store.find_active_by_id(
                stored.grant_id, binding(tenant="tenant-2"), generation=1, now=NOW
            )
            is None
        )
        assert (
            await grant_store.find_active_by_id(
                stored.grant_id, stored.binding, generation=2, now=NOW
            )
            is None
        )
        assert (
            await grant_store.find_active_by_id("mpg_missing", stored.binding, generation=1, now=NOW)
            is None
        )

    async def test_get_by_id_ignores_generation_and_active_status_but_not_binding(
        self, grant_store: ModelProxyGrantStore
    ) -> None:
        stored = await grant_store.insert_active(draft("get-exact"), now=NOW)

        assert await grant_store.get_by_id(stored.grant_id, binding(root="root-2")) is None
        assert await grant_store.get_by_id("mpg_missing", stored.binding) is None
        assert await grant_store.get_by_id(stored.grant_id, stored.binding) == stored

    async def test_identifier_and_digest_collisions_are_redacted(
        self, grant_store: ModelProxyGrantStore
    ) -> None:
        stored = await grant_store.insert_active(draft("collision-original"), now=NOW)
        duplicate_id = draft("collision-original", binding_value=binding(cell="cell-dup-id"))
        duplicate_bearer = draft(
            "collision-bearer",
            binding_value=binding(cell="cell-dup-bearer"),
            bearer_name="bearer-collision-original",
        )
        duplicate_request = draft(
            "collision-request",
            binding_value=binding(cell="cell-dup-request"),
            request_name="request-collision-original",
        )

        for collision in (duplicate_id, duplicate_bearer, duplicate_request):
            with pytest.raises(ModelProxyGrantConflict, match="already inserted") as caught:
                await grant_store.insert_active(collision, now=NOW)
            assert collision.bearer_digest not in str(caught.value)
            assert collision.startup_request_digest not in str(caught.value)
            assert collision.grant_id not in str(caught.value)
        assert await grant_store.get_by_id(stored.grant_id, stored.binding) == stored

    async def test_same_generation_conflict_and_stale_generation_fence(
        self, grant_store: ModelProxyGrantStore
    ) -> None:
        first = await grant_store.insert_active(draft("gen-first", generation=1), now=NOW)

        with pytest.raises(ActiveModelProxyGenerationConflict):
            await grant_store.insert_active(draft("gen-same", generation=1), now=NOW)

        second = await grant_store.insert_active(draft("gen-second", generation=2), now=NOW)
        assert second.generation == 2
        stored_first = await grant_store.get_by_id(first.grant_id, first.binding)
        assert stored_first is not None
        assert stored_first.status is ModelProxyGrantStatus.REVOKED
        assert stored_first.revocation_reason == "superseded_generation"

        with pytest.raises(StaleModelProxyGeneration):
            await grant_store.insert_active(draft("gen-stale", generation=1), now=NOW)

    @pytest.mark.parametrize("level", ["root", "phase", "assignment", "cell"])
    async def test_hierarchical_cancellation_is_scoped_immediate_and_terminal(
        self, grant_store: ModelProxyGrantStore, level: str
    ) -> None:
        target_binding = binding()
        foreign_binding = {
            "root": binding(root="root-2"),
            "phase": binding(phase="phase-2"),
            "assignment": binding(assignment="assignment-2"),
            "cell": binding(cell="cell-2", pid=4330),
        }[level]
        target = await grant_store.insert_active(
            draft("cancel-target", binding_value=target_binding), now=NOW
        )
        foreign = await grant_store.insert_active(
            draft("cancel-foreign", binding_value=foreign_binding), now=NOW
        )
        scope = {
            "root": target_binding.cell.assignment.phase.root,
            "phase": target_binding.cell.assignment.phase,
            "assignment": target_binding.cell.assignment,
            "cell": target_binding.cell,
        }[level]
        revoke = getattr(grant_store, f"revoke_{level}")

        assert await revoke(scope, reason=f"{level}_cancelled", now=NOW) == 1
        assert (
            await grant_store.find_active_by_id(
                target.grant_id, target_binding, generation=1, now=NOW
            )
            is None
        )
        assert (
            await grant_store.find_active_by_id(
                foreign.grant_id, foreign_binding, generation=1, now=NOW
            )
            == foreign
        )
        stored_target = await grant_store.get_by_id(target.grant_id, target_binding)
        assert stored_target is not None
        assert stored_target.status is ModelProxyGrantStatus.REVOKED
        assert stored_target.revocation_reason == f"{level}_cancelled"

        with pytest.raises(StaleModelProxyGeneration):
            await grant_store.insert_active(
                draft("cancel-target-next", binding_value=target_binding, generation=2), now=NOW
            )

    async def test_expiry_hides_from_active_lookups_and_fence_survives(
        self, grant_store: ModelProxyGrantStore
    ) -> None:
        stored = await grant_store.insert_active(draft("expiring", ttl_seconds=1), now=NOW)
        expiry = NOW + timedelta(seconds=1)

        assert (
            await grant_store.find_active_by_id(
                stored.grant_id, stored.binding, generation=1, now=expiry
            )
            is None
        )
        materialized = await grant_store.get_by_id(stored.grant_id, stored.binding)
        assert materialized is not None
        assert materialized.status is ModelProxyGrantStatus.EXPIRED

        with pytest.raises(StaleModelProxyGeneration):
            await grant_store.insert_active(draft("expiring-replay", ttl_seconds=1), now=expiry)

        replacement = await grant_store.insert_active(
            draft("expiring-next", ttl_seconds=1, generation=2), now=expiry
        )
        assert replacement.generation == 2

    async def test_invalid_revocation_reason_is_rejected_without_mutation(
        self, grant_store: ModelProxyGrantStore
    ) -> None:
        stored = await grant_store.insert_active(draft("bad-reason"), now=NOW)

        with pytest.raises(ValueError, match="safe ASCII"):
            await grant_store.revoke_cell(stored.binding.cell, reason="invalid\nreason", now=NOW)
        assert await grant_store.get_by_id(stored.grant_id, stored.binding) == stored

    async def test_malformed_identifiers_and_digests_return_none_without_raising(
        self, grant_store: ModelProxyGrantStore
    ) -> None:
        stored = await grant_store.insert_active(draft("malformed-lookup"), now=NOW)

        assert await grant_store.get_by_id("mpg_missing", stored.binding) is None
        assert (
            await grant_store.find_active_by_id(
                "mpg_missing", stored.binding, generation=1, now=NOW
            )
            is None
        )
        assert (
            await grant_store.find_active_for_trusted_observation(
                "not-a-digest", observation(stored.binding), generation=1, now=NOW
            )
            is None
        )

    async def test_store_guards_reject_wrong_scope_and_input_types(
        self, grant_store: ModelProxyGrantStore
    ) -> None:
        exact = binding()
        with pytest.raises(TypeError, match="exact ModelProxyRootScope"):
            await grant_store.revoke_root(
                exact.cell.assignment.phase,  # type: ignore[arg-type]
                reason="wrong-type",
                now=NOW,
            )
        with pytest.raises(TypeError, match="exact ModelProxyPhaseScope"):
            await grant_store.revoke_phase(
                exact.cell.assignment,  # type: ignore[arg-type]
                reason="wrong-type",
                now=NOW,
            )
        with pytest.raises(TypeError, match="exact ModelProxyAssignmentScope"):
            await grant_store.revoke_assignment(
                exact.cell,  # type: ignore[arg-type]
                reason="wrong-type",
                now=NOW,
            )
        with pytest.raises(TypeError, match="exact ModelProxyCellScope"):
            await grant_store.revoke_cell(exact, reason="wrong-type", now=NOW)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="exact ModelProxyGrantDraft"):
            await grant_store.insert_active(exact, now=NOW)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="exact ModelProxyGrantBinding"):
            await grant_store.get_by_id("mpg_x", exact.cell)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="exact ModelProxyGrantBinding"):
            await grant_store.find_active_by_id(
                "mpg_x", exact.cell, generation=1, now=NOW  # type: ignore[arg-type]
            )
        with pytest.raises(TypeError, match="exact TrustedModelProxyRequestObservation"):
            await grant_store.find_active_for_trusted_observation(
                "a" * 64, exact, generation=1, now=NOW  # type: ignore[arg-type]
            )


__all__ = [
    "ModelProxyGrantStoreContract",
    "NOW",
    "binding",
    "draft",
    "foreign_bindings",
    "observation",
]
