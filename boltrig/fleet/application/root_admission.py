"""Governed admission that fuses root routing with insert-once persistence."""

from __future__ import annotations

from boltrig.fleet.application.codex_routing import CodexRolloutRouter
from boltrig.fleet.domain.codex_rollout import (
    CodexRolloutPolicy,
    RootEngineDecision,
    RootRoutingFacts,
)
from boltrig.fleet.ports.root_engine_decisions import (
    RootEngineDecisionInsertStatus,
    RootEngineDecisionStore,
)


class RootRoutingAdmission:
    """The sole atomic, total path from trusted root facts to a persisted decision.

    A root never reaches execution on a router output alone: routing and insert-once
    persistence are one operation. The first caller for a scope inserts the routed
    decision; every later caller for the same trusted facts receives the exact same
    persisted object; and a caller whose facts drifted from immutable history is
    rejected without overwriting it. There is no route-only or peek surface.
    """

    __slots__ = ("_router", "_store")

    def __init__(
        self,
        policy: CodexRolloutPolicy,
        store: RootEngineDecisionStore,
    ) -> None:
        # The router exact-validates the policy; the store is a Protocol dependency
        # and is exercised through its own insert_once/get contract, not type-checked.
        self._router = CodexRolloutRouter(policy)
        self._store = store

    def __repr__(self) -> str:
        return "RootRoutingAdmission()"

    async def admit(self, facts: RootRoutingFacts) -> RootEngineDecision:
        """Persist exactly one authoritative decision per root, or replay it verbatim."""
        if type(facts) is not RootRoutingFacts:
            raise TypeError("facts must be an exact RootRoutingFacts")
        existing = await self._store.get(facts.scope)
        if existing is not None:
            return self._router.decide(facts, persisted_decision=existing)
        decision = self._router.decide(facts)
        result = await self._store.insert_once(decision)
        if result.status is RootEngineDecisionInsertStatus.INSERTED:
            return result.decision
        # A concurrent racer inserted a canonically-equal decision for this root.
        # Re-bind to the persisted object so every caller shares one identity, and
        # re-validate it against the trusted facts through the single router path so
        # a store that returned REPLAYED for a divergent decision fails closed.
        return self._router.decide(facts, persisted_decision=result.decision)


__all__ = ["RootRoutingAdmission"]
