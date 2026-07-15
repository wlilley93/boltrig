"""Production in-memory root-engine decision adapter tests."""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError

import pytest

from boltrig.fleet.infrastructure.memory_root_engine_decisions import (
    HARD_MAX_ROOT_ENGINE_DECISIONS,
    MemoryRootEngineDecisionStore,
)
from boltrig.fleet.ports.root_engine_decisions import (
    RootEngineDecisionCapacityExceeded,
    RootEngineDecisionConflict,
    RootEngineDecisionInsertResult,
    RootEngineDecisionInsertStatus,
    RootEngineDecisionStore,
)
from boltrig.fleet.domain.codex_rollout import RootEngineDecision
from tests.contracts.root_engine_decision_store import (
    assert_concurrent_exact_replay_is_serializable,
    assert_insert_once_replay_conflict_and_scope,
    changed_decisions,
    decision,
    scope,
)


async def test_insert_once_exact_replay_changed_facts_and_exact_scope() -> None:
    store: RootEngineDecisionStore = MemoryRootEngineDecisionStore()

    await assert_insert_once_replay_conflict_and_scope(store)


async def test_concurrent_create_has_one_insert_and_only_exact_replays() -> None:
    store: RootEngineDecisionStore = MemoryRootEngineDecisionStore()

    await assert_concurrent_exact_replay_is_serializable(store)


async def test_concurrent_conflicting_create_has_one_winner_without_overwrite() -> None:
    store = MemoryRootEngineDecisionStore()
    first = decision()
    second = changed_decisions(first)[0]

    async def attempt(
        candidate: RootEngineDecision,
    ) -> RootEngineDecisionInsertResult | RootEngineDecisionConflict:
        try:
            return await store.insert_once(candidate)
        except RootEngineDecisionConflict as error:
            return error

    outcomes = await asyncio.gather(attempt(first), attempt(second))

    inserted = [
        outcome
        for outcome in outcomes
        if not isinstance(outcome, RootEngineDecisionConflict)
    ]
    assert len(inserted) == 1
    assert inserted[0].status is RootEngineDecisionInsertStatus.INSERTED
    assert sum(isinstance(item, RootEngineDecisionConflict) for item in outcomes) == 1
    assert await store.get(first.scope) is inserted[0].decision


async def test_capacity_backpressure_never_evicts_or_masks_replay_conflict() -> None:
    store = MemoryRootEngineDecisionStore(max_decisions=1)
    original = decision()
    changed = changed_decisions(original)[0]
    foreign = decision(scope("root-2"))
    assert (await store.insert_once(original)).status is RootEngineDecisionInsertStatus.INSERTED

    assert (await store.insert_once(original)).status is RootEngineDecisionInsertStatus.REPLAYED
    with pytest.raises(RootEngineDecisionConflict):
        await store.insert_once(changed)
    with pytest.raises(RootEngineDecisionCapacityExceeded):
        await store.insert_once(foreign)

    assert await store.get(original.scope) is original
    assert await store.get(foreign.scope) is None


@pytest.mark.parametrize(
    "value",
    [0, True, -1, HARD_MAX_ROOT_ENGINE_DECISIONS + 1],
)
def test_capacity_configuration_is_strictly_bounded(value: int) -> None:
    with pytest.raises(ValueError, match="between"):
        MemoryRootEngineDecisionStore(max_decisions=value)


async def test_reads_require_full_exact_scope_and_no_global_lookup_exists() -> None:
    store = MemoryRootEngineDecisionStore()
    original = decision()
    await store.insert_once(original)
    other_tenant = decision(scope(tenant_id="tenant-2"))
    other_workspace = decision(scope(workspace_id="workspace-2"))
    await store.insert_once(other_tenant)
    await store.insert_once(other_workspace)

    assert await store.get(original.scope) is original
    assert await store.get(other_tenant.scope) is other_tenant
    assert await store.get(other_workspace.scope) is other_workspace
    assert await store.get(scope("root-2")) is None
    with pytest.raises(TypeError, match="exact RootRouteScope"):
        await store.get("root-1")  # type: ignore[arg-type]
    assert {
        name
        for name in RootEngineDecisionStore.__dict__
        if not name.startswith("_")
    } == {"get", "insert_once"}
    assert not hasattr(store, "get_by_root_id")
    assert not hasattr(store, "list")


async def test_repr_results_and_conflicts_disclose_no_routing_identifiers() -> None:
    store = MemoryRootEngineDecisionStore()
    original = decision(
        scope(
            "root-sensitive",
            tenant_id="tenant-sensitive",
            workspace_id="workspace-sensitive",
        )
    )
    result = await store.insert_once(original)
    changed = changed_decisions(original)[0]

    with pytest.raises(RootEngineDecisionConflict) as captured:
        await store.insert_once(changed)

    rendered = " ".join((repr(store), repr(result), str(captured.value), repr(captured.value)))
    for secret in (
        original.scope.tenant_id,
        original.scope.workspace_id,
        original.scope.root_run_id,
        original.digest,
        original.policy_digest,
    ):
        assert secret not in rendered
    with pytest.raises(FrozenInstanceError):
        result.status = RootEngineDecisionInsertStatus.REPLAYED  # type: ignore[misc]


async def test_adapter_rejects_non_exact_decision_values() -> None:
    store = MemoryRootEngineDecisionStore()

    with pytest.raises(TypeError, match="exact RootEngineDecision"):
        await store.insert_once(object())  # type: ignore[arg-type]
