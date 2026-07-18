"""Bounded atomic in-memory storage for immutable root-engine decisions."""

from __future__ import annotations

import asyncio
import hmac
from dataclasses import dataclass, field

from boltrig.fleet.domain.codex_rollout import RootEngineDecision, RootRouteScope
from boltrig.fleet.ports.root_engine_decisions import (
    RootEngineDecisionCapacityExceeded,
    RootEngineDecisionConflict,
    RootEngineDecisionInsertResult,
    RootEngineDecisionInsertStatus,
)

DEFAULT_MAX_ROOT_ENGINE_DECISIONS = 4_096
HARD_MAX_ROOT_ENGINE_DECISIONS = 100_000


@dataclass(frozen=True, slots=True)
class _StoredDecision:
    decision: RootEngineDecision = field(repr=False)
    digest: str = field(repr=False)


class MemoryRootEngineDecisionStore:
    """Serializable non-evicting reference adapter with bounded backpressure."""

    __slots__ = ("_lock", "_max_decisions", "_records")

    def __init__(
        self, *, max_decisions: int = DEFAULT_MAX_ROOT_ENGINE_DECISIONS
    ) -> None:
        self._max_decisions = _capacity(max_decisions)
        self._records: dict[RootRouteScope, _StoredDecision] = {}
        self._lock = asyncio.Lock()

    def __repr__(self) -> str:
        return "MemoryRootEngineDecisionStore(bounded=True)"

    async def insert_once(
        self, decision: RootEngineDecision
    ) -> RootEngineDecisionInsertResult:
        if type(decision) is not RootEngineDecision:
            raise TypeError("decision must be an exact RootEngineDecision")
        incoming_digest = decision.digest
        async with self._lock:
            existing = self._records.get(decision.scope)
            if existing is not None:
                if existing.decision == decision and hmac.compare_digest(
                    existing.digest, incoming_digest
                ):
                    return RootEngineDecisionInsertResult(
                        RootEngineDecisionInsertStatus.REPLAYED,
                        existing.decision,
                    )
                raise RootEngineDecisionConflict(
                    "root engine decision conflicts with immutable history"
                )
            if len(self._records) >= self._max_decisions:
                raise RootEngineDecisionCapacityExceeded(
                    "root engine decision store capacity exceeded"
                )
            self._records[decision.scope] = _StoredDecision(decision, incoming_digest)
            return RootEngineDecisionInsertResult(
                RootEngineDecisionInsertStatus.INSERTED,
                decision,
            )

    async def get(self, scope: RootRouteScope) -> RootEngineDecision | None:
        if type(scope) is not RootRouteScope:
            raise TypeError("scope must be an exact RootRouteScope")
        async with self._lock:
            stored = self._records.get(scope)
            return None if stored is None else stored.decision


def _capacity(value: object) -> int:
    if type(value) is not int or not 1 <= value <= HARD_MAX_ROOT_ENGINE_DECISIONS:
        raise ValueError(
            f"max_decisions must be between 1 and {HARD_MAX_ROOT_ENGINE_DECISIONS}"
        )
    return value


__all__ = [
    "DEFAULT_MAX_ROOT_ENGINE_DECISIONS",
    "HARD_MAX_ROOT_ENGINE_DECISIONS",
    "MemoryRootEngineDecisionStore",
]
