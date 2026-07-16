"""Production in-memory capability attestation adapter tests."""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError

import pytest

from boltrig.fleet.infrastructure.memory_capability_attestations import (
    HARD_MAX_CAPABILITY_ATTESTATION_SETS,
    MemoryCapabilityAttestationStore,
)
from boltrig.fleet.ports.capability_attestations import (
    CapabilityAttestationCapacityExceeded,
    CapabilityAttestationConflict,
    CapabilityAttestationInsertResult,
    CapabilityAttestationInsertStatus,
    CapabilityAttestationStore,
)
from tests.contracts.capability_attestation_store import (
    assert_concurrent_exact_replay_is_serializable,
    assert_insert_once_replay_conflict_and_resolve,
    attestation_set,
    changed_sets,
    pin,
)
from tests.contracts.grant_lease_fixtures import binding


async def test_insert_once_exact_replay_conflict_and_fail_closed_resolve() -> None:
    store: CapabilityAttestationStore = MemoryCapabilityAttestationStore()

    await assert_insert_once_replay_conflict_and_resolve(store)


async def test_concurrent_create_has_one_insert_and_only_exact_replays() -> None:
    store: CapabilityAttestationStore = MemoryCapabilityAttestationStore()

    await assert_concurrent_exact_replay_is_serializable(store)


async def test_concurrent_conflicting_create_has_one_winner_without_overwrite() -> None:
    store = MemoryCapabilityAttestationStore()
    first = attestation_set()
    second = changed_sets(first)[0]

    async def attempt(
        candidate: object,
    ) -> CapabilityAttestationInsertResult | CapabilityAttestationConflict:
        try:
            return await store.insert_once(candidate)  # type: ignore[arg-type]
        except CapabilityAttestationConflict as error:
            return error

    outcomes = await asyncio.gather(attempt(first), attempt(second))

    inserted = [
        outcome
        for outcome in outcomes
        if not isinstance(outcome, CapabilityAttestationConflict)
    ]
    assert len(inserted) == 1
    assert inserted[0].status is CapabilityAttestationInsertStatus.INSERTED
    assert sum(isinstance(item, CapabilityAttestationConflict) for item in outcomes) == 1
    assert await store.resolve_capability_attestations(pin(first)) == first


async def test_capacity_backpressure_never_evicts_or_masks_replay_conflict() -> None:
    store = MemoryCapabilityAttestationStore(max_sets=1)
    original = attestation_set()
    changed = changed_sets(original)[0]
    foreign = attestation_set(scope=binding(assignment="assignment-2"))
    assert (await store.insert_once(original)).status is CapabilityAttestationInsertStatus.INSERTED

    assert (await store.insert_once(original)).status is CapabilityAttestationInsertStatus.REPLAYED
    with pytest.raises(CapabilityAttestationConflict):
        await store.insert_once(changed)
    with pytest.raises(CapabilityAttestationCapacityExceeded):
        await store.insert_once(foreign)

    assert await store.resolve_capability_attestations(pin(original)) == original
    assert await store.resolve_capability_attestations(pin(foreign)) is None


@pytest.mark.parametrize(
    "value",
    [0, True, -1, HARD_MAX_CAPABILITY_ATTESTATION_SETS + 1],
)
def test_capacity_configuration_is_strictly_bounded(value: int) -> None:
    with pytest.raises(ValueError, match="between"):
        MemoryCapabilityAttestationStore(max_sets=value)


async def test_adapter_rejects_non_exact_values() -> None:
    store = MemoryCapabilityAttestationStore()

    with pytest.raises(TypeError, match="exact AssignmentCapabilityAttestationSet"):
        await store.insert_once(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="exact AssignmentCapabilityAttestationPin"):
        await store.resolve_capability_attestations(object())  # type: ignore[arg-type]


async def test_result_is_immutable_and_store_repr_discloses_no_evidence() -> None:
    store = MemoryCapabilityAttestationStore()
    result = await store.insert_once(attestation_set())

    assert repr(store) == "MemoryCapabilityAttestationStore(bounded=True)"
    with pytest.raises(FrozenInstanceError):
        result.status = CapabilityAttestationInsertStatus.REPLAYED  # type: ignore[misc]
