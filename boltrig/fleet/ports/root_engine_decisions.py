"""Insert-once persistence boundary for immutable root-engine decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from boltrig.fleet.domain.codex_rollout import RootEngineDecision, RootRouteScope


class RootEngineDecisionStoreError(RuntimeError):
    """A routing decision could not be retained without weakening history."""


class RootEngineDecisionConflict(RootEngineDecisionStoreError):
    """An exact root already owns a different immutable routing decision."""


class RootEngineDecisionCapacityExceeded(RootEngineDecisionStoreError):
    """The bounded decision store cannot retain another immutable root."""


class RootEngineDecisionInsertStatus(str, Enum):
    """Only a fresh insert and an exact replay are successful outcomes."""

    INSERTED = "inserted"
    REPLAYED = "replayed"


@dataclass(frozen=True, slots=True)
class RootEngineDecisionInsertResult:
    """A sanitized write result carrying the exact retained decision."""

    status: RootEngineDecisionInsertStatus
    decision: RootEngineDecision = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.status) is not RootEngineDecisionInsertStatus:
            raise TypeError("status must be an exact RootEngineDecisionInsertStatus")
        if type(self.decision) is not RootEngineDecision:
            raise TypeError("decision must be an exact RootEngineDecision")


class RootEngineDecisionStore(Protocol):
    """Exact-scope persistence with no global root-id lookup surface."""

    async def insert_once(
        self, decision: RootEngineDecision
    ) -> RootEngineDecisionInsertResult:
        """Insert once, replay an exact canonical decision, or conflict atomically."""
        ...

    async def get(self, scope: RootRouteScope) -> RootEngineDecision | None:
        """Read only through the exact tenant, workspace, and root scope."""
        ...


__all__ = [
    "RootEngineDecisionCapacityExceeded",
    "RootEngineDecisionConflict",
    "RootEngineDecisionInsertResult",
    "RootEngineDecisionInsertStatus",
    "RootEngineDecisionStore",
    "RootEngineDecisionStoreError",
]
