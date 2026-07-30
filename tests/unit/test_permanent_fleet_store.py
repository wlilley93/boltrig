"""Memory permanent-fleet observation contract."""

from __future__ import annotations

import pytest

from boltrig.models import PermanentFleetObservation, utcnow
from boltrig.store import InMemoryStore


@pytest.mark.invariant("SEC-WRK-27")
async def test_memory_observation_is_tenant_scoped_and_latest_per_worker():
    store = InMemoryStore()
    first = PermanentFleetObservation(
        tenant_id="one",
        worker_id="worker-1",
        generation="pf_" + "a" * 24,
        status="degraded",
        applied_fields=[],
        inactive_fields=["purpose"],
        observed_at=utcnow(),
    )
    latest = PermanentFleetObservation(
        tenant_id="one",
        worker_id="worker-1",
        generation="pf_" + "b" * 24,
        status="applied",
        applied_fields=["department_routing_identity"],
        inactive_fields=["purpose"],
        observed_at=utcnow(),
    )
    other = PermanentFleetObservation(
        tenant_id="two",
        worker_id="worker-1",
        generation="pf_" + "c" * 24,
        status="applied",
        applied_fields=["department_routing_identity"],
        inactive_fields=[],
        observed_at=utcnow(),
    )
    await store.upsert_permanent_fleet_observation(first)
    await store.upsert_permanent_fleet_observation(latest)
    await store.upsert_permanent_fleet_observation(other)

    rows = await store.list_permanent_fleet_observations("one")
    assert [(row.worker_id, row.generation) for row in rows] == [
        ("worker-1", latest.generation)
    ]


@pytest.mark.invariant("SEC-WRK-27")
def test_observation_contract_rejects_false_or_overlapping_evidence():
    with pytest.raises(ValueError):
        PermanentFleetObservation(
            tenant_id="one",
            worker_id="worker-1",
            generation="not-a-generation",
            status="applied",
        )
    with pytest.raises(ValueError):
        PermanentFleetObservation(
            tenant_id="one",
            worker_id="worker-1",
            generation="pf_" + "a" * 24,
            status="applied",
            applied_fields=["purpose"],
            inactive_fields=["purpose"],
        )
