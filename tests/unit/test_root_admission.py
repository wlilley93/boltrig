"""Production memory-store root admission service tests."""

from __future__ import annotations

import asyncio

import pytest

from boltrig.fleet.application.codex_routing import (
    RootDecisionConflict,
    StaleRolloutGeneration,
)
from boltrig.fleet.application.root_admission import RootRoutingAdmission
from boltrig.fleet.domain.codex_rollout import (
    CodexCompatibility,
    CodexRolloutMode,
    CodexRolloutPolicy,
    EngineRoute,
    ExecutionResultSource,
    RootWorkload,
    RoutingReason,
)
from boltrig.fleet.infrastructure.memory_root_engine_decisions import (
    MemoryRootEngineDecisionStore,
)
from boltrig.fleet.ports.root_engine_decisions import RootEngineDecisionStore
from tests.contracts.root_admission import (
    assert_root_admission_is_atomic_and_total,
    assert_root_admission_is_scope_isolated,
    facts,
    scope,
)


def _build(
    policy: CodexRolloutPolicy,
) -> tuple[RootRoutingAdmission, RootEngineDecisionStore]:
    store: RootEngineDecisionStore = MemoryRootEngineDecisionStore()
    return RootRoutingAdmission(policy, store), store


@pytest.mark.invariant("SEC-162")
async def test_root_admission_persists_one_decision_and_replays_the_same_object() -> None:
    await assert_root_admission_is_atomic_and_total(_build)


@pytest.mark.invariant("SEC-162")
async def test_concurrent_admission_resolves_to_one_persisted_identity() -> None:
    admission, store = _build(CodexRolloutPolicy(1, mode=CodexRolloutMode.DEFAULT))
    target = scope("root-race")

    outcomes = await asyncio.gather(
        *(admission.admit(facts("root-race")) for _ in range(64))
    )

    assert len({id(item) for item in outcomes}) == 1
    winner = outcomes[0]
    assert await store.get(target) is winner
    # A later, sequential admit still returns the identical persisted object.
    assert await admission.admit(facts("root-race")) is winner


@pytest.mark.invariant("SEC-162")
async def test_drifted_root_facts_are_rejected_without_overwrite() -> None:
    admission, store = _build(CodexRolloutPolicy(1, mode=CodexRolloutMode.DEFAULT))
    original_facts = facts("root-1")
    original = await admission.admit(original_facts)

    with pytest.raises(RootDecisionConflict, match="facts changed"):
        await admission.admit(facts("root-1", workload=RootWorkload.WRITE_CAPABLE))

    assert await store.get(original_facts.scope) is original


@pytest.mark.invariant("SEC-162")
def test_admission_exposes_no_route_only_or_peek_bypass() -> None:
    public = {
        name for name in vars(RootRoutingAdmission) if not name.startswith("_")
    }

    assert public == {"admit"}


async def test_root_admission_keeps_independent_roots_scope_isolated() -> None:
    await assert_root_admission_is_scope_isolated(_build)


async def test_stale_policy_generation_is_rejected_for_a_new_root() -> None:
    admission, _store = _build(CodexRolloutPolicy(9, mode=CodexRolloutMode.DEFAULT))

    with pytest.raises(StaleRolloutGeneration, match="stale"):
        await admission.admit(facts("root-1", generation=8))


async def test_router_decisions_are_preserved_through_admission() -> None:
    default_admission, _ = _build(CodexRolloutPolicy(3, mode=CodexRolloutMode.DEFAULT))
    rollback_admission, _ = _build(
        CodexRolloutPolicy(4, mode=CodexRolloutMode.DEFAULT, emergency_rollback=True)
    )

    eligible = await default_admission.admit(facts("root-eligible", generation=3))
    ineligible = await default_admission.admit(
        facts("root-ineligible", generation=3, compatibility=CodexCompatibility.INELIGIBLE)
    )
    rolled_back = await rollback_admission.admit(facts("root-rolled-back", generation=4))

    assert eligible.route is EngineRoute.CODEX_APP_SERVER
    assert eligible.execution_result_source is ExecutionResultSource.CODEX_APP_SERVER
    assert eligible.reason_code is RoutingReason.DEFAULT_SELECTED
    assert ineligible.route is EngineRoute.LEGACY
    assert ineligible.reason_code is RoutingReason.ROOT_INELIGIBLE
    assert rolled_back.route is EngineRoute.LEGACY
    assert rolled_back.reason_code is RoutingReason.EMERGENCY_ROLLBACK


async def test_admit_rejects_non_exact_facts() -> None:
    admission, _ = _build(CodexRolloutPolicy(1))

    with pytest.raises(TypeError, match="exact RootRoutingFacts"):
        await admission.admit(object())  # type: ignore[arg-type]


def test_repr_discloses_no_routing_identifiers() -> None:
    admission, _ = _build(CodexRolloutPolicy(1, mode=CodexRolloutMode.DEFAULT))

    rendered = repr(admission)

    assert rendered == "RootRoutingAdmission()"
