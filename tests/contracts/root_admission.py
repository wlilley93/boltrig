"""Reusable behavior checks for the atomic, total root admission service."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from boltrig.fleet.application.codex_routing import RootDecisionConflict
from boltrig.fleet.application.root_admission import RootRoutingAdmission
from boltrig.fleet.domain.codex_rollout import (
    CodexCompatibility,
    CodexRolloutMode,
    CodexRolloutPolicy,
    RootRouteScope,
    RootRoutingFacts,
    RootWorkload,
)
from boltrig.fleet.ports.root_engine_decisions import RootEngineDecisionStore

_POLICY = CodexRolloutPolicy(1, mode=CodexRolloutMode.DEFAULT)


def scope(
    root_run_id: str = "root-1",
    *,
    tenant_id: str = "tenant-1",
    workspace_id: str = "workspace-1",
) -> RootRouteScope:
    return RootRouteScope(tenant_id, workspace_id, root_run_id)


def facts(
    root_run_id: str = "root-1",
    *,
    tenant_id: str = "tenant-1",
    workspace_id: str = "workspace-1",
    workload: RootWorkload = RootWorkload.BOUNDED_READ_ONLY,
    compatibility: CodexCompatibility = CodexCompatibility.ELIGIBLE,
    generation: int = 1,
) -> RootRoutingFacts:
    return RootRoutingFacts(
        scope(root_run_id, tenant_id=tenant_id, workspace_id=workspace_id),
        generation,
        workload,
        compatibility,
    )


# A fixture binds a fresh policy to a fresh store and returns both so the contract
# can prove the persisted record, not just the returned object.
AdmissionFixture = Callable[
    [CodexRolloutPolicy], "tuple[RootRoutingAdmission, RootEngineDecisionStore]"
]


async def assert_root_admission_is_atomic_and_total(build: AdmissionFixture) -> None:
    admission, store = build(_POLICY)
    first_facts = facts("root-1")

    # A new root is routed AND persisted in one operation; the returned object is the
    # single record the store retains.
    first = await admission.admit(first_facts)
    assert await store.get(first_facts.scope) is first

    # Re-admitting the same trusted facts returns the exact same object without
    # creating a second record (totality: one immutable decision per root).
    replayed = await admission.admit(first_facts)
    assert replayed is first

    # Concurrent admission of one root resolves to a single winner and exact replays;
    # every caller receives the identical persisted object.
    concurrent_scope = scope("root-concurrent")
    concurrent = await asyncio.gather(
        *(admission.admit(facts("root-concurrent")) for _ in range(32))
    )
    assert len({id(item) for item in concurrent}) == 1
    winner = concurrent[0]
    assert await store.get(concurrent_scope) is winner

    # Facts that drifted from immutable history are rejected without overwrite.
    try:
        await admission.admit(facts("root-1", workload=RootWorkload.WRITE_CAPABLE))
    except RootDecisionConflict:
        pass
    else:  # pragma: no cover - a broken service reaches the assertion
        raise AssertionError("drifted root routing facts were admitted without conflict")
    assert await store.get(first_facts.scope) is first


async def assert_root_admission_is_scope_isolated(build: AdmissionFixture) -> None:
    admission, store = build(_POLICY)

    one = await admission.admit(facts("root-a"))
    two = await admission.admit(facts("root-b"))

    assert one is not two
    assert one.scope != two.scope
    assert await store.get(scope("root-a")) is one
    assert await store.get(scope("root-b")) is two


__all__ = [
    "AdmissionFixture",
    "assert_root_admission_is_atomic_and_total",
    "assert_root_admission_is_scope_isolated",
    "facts",
    "scope",
]
