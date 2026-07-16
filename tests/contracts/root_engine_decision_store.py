"""Reusable behavior checks for every RootEngineDecisionStore adapter."""

from __future__ import annotations

import asyncio
from dataclasses import replace

from boltrig.fleet.application.codex_routing import CodexRolloutRouter
from boltrig.fleet.domain.codex_rollout import (
    CanaryScope,
    CodexCompatibility,
    CodexRolloutMode,
    CodexRolloutPolicy,
    RootEngineDecision,
    RootRouteScope,
    RootRoutingFacts,
    RootWorkload,
)
from boltrig.fleet.ports.root_engine_decisions import (
    RootEngineDecisionConflict,
    RootEngineDecisionInsertStatus,
    RootEngineDecisionStore,
)

_CANARY_KEY = b"root-decision-store-contract-key-01"


def scope(
    root_run_id: str = "root-1",
    *,
    tenant_id: str = "tenant-1",
    workspace_id: str = "workspace-1",
) -> RootRouteScope:
    return RootRouteScope(tenant_id, workspace_id, root_run_id)


def decision(
    owner: RootRouteScope | None = None,
    *,
    generation: int = 1,
    mode: CodexRolloutMode = CodexRolloutMode.DEFAULT,
    workload: RootWorkload = RootWorkload.BOUNDED_READ_ONLY,
    compatibility: CodexCompatibility = CodexCompatibility.ELIGIBLE,
) -> RootEngineDecision:
    target = owner or scope()
    kwargs: dict[str, object] = {}
    if mode is CodexRolloutMode.CANARY:
        kwargs = {
            "canary_percentage": 100,
            "canary_allowlist": (
                CanaryScope(target.tenant_id, target.workspace_id),
            ),
            "canary_hash_key": _CANARY_KEY,
        }
    policy = CodexRolloutPolicy(generation, mode=mode, **kwargs)  # type: ignore[arg-type]
    facts = RootRoutingFacts(target, generation, workload, compatibility)
    return CodexRolloutRouter(policy).decide(facts)


def changed_decisions(original: RootEngineDecision) -> tuple[RootEngineDecision, ...]:
    """Return valid same-scope decisions changing every persisted fact family."""

    return (
        replace(original, workload=RootWorkload.WRITE_CAPABLE),
        decision(original.scope, compatibility=CodexCompatibility.INELIGIBLE),
        replace(original, policy_generation=2),
        replace(original, policy_digest="sha256:" + "f" * 64),
        decision(original.scope, mode=CodexRolloutMode.OFF),
        decision(original.scope, mode=CodexRolloutMode.CANARY),
    )


async def assert_insert_once_replay_conflict_and_scope(
    store: RootEngineDecisionStore,
) -> None:
    original = decision()
    exact_copy = replace(original)
    assert exact_copy == original and exact_copy is not original
    assert exact_copy.digest == original.digest
    inserted = await store.insert_once(original)
    replayed = await store.insert_once(exact_copy)

    assert inserted.status is RootEngineDecisionInsertStatus.INSERTED
    assert replayed.status is RootEngineDecisionInsertStatus.REPLAYED
    # The inserter always receives its own object back by identity. A replay or a
    # later read returns the canonical decision value: the in-memory adapter happens
    # to preserve identity, a durable adapter reconstructs an equal value, so the
    # shared contract binds on canonical equality, not object identity.
    assert inserted.decision is original
    assert replayed.decision == original
    assert await store.get(original.scope) == original

    for changed in changed_decisions(original):
        assert changed.scope == original.scope
        assert changed.digest != original.digest
        try:
            await store.insert_once(changed)
        except RootEngineDecisionConflict:
            pass
        else:  # pragma: no cover - a broken adapter reaches the assertion
            raise AssertionError("changed immutable routing history did not conflict")
        assert await store.get(original.scope) == original

    for foreign in (
        scope(tenant_id="tenant-2"),
        scope(workspace_id="workspace-2"),
        scope("root-2"),
    ):
        assert await store.get(foreign) is None


async def assert_concurrent_exact_replay_is_serializable(
    store: RootEngineDecisionStore,
) -> None:
    original = decision()
    outcomes = await asyncio.gather(
        *(store.insert_once(original) for _ in range(32))
    )

    statuses = [outcome.status for outcome in outcomes]
    assert statuses.count(RootEngineDecisionInsertStatus.INSERTED) == 1
    assert statuses.count(RootEngineDecisionInsertStatus.REPLAYED) == 31
    assert all(outcome.decision == original for outcome in outcomes)
    assert await store.get(original.scope) == original


__all__ = [
    "assert_concurrent_exact_replay_is_serializable",
    "assert_insert_once_replay_conflict_and_scope",
    "changed_decisions",
    "decision",
    "scope",
]
