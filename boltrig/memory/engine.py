"""The engine-agnostic Memory Engine interface (MEM-ENG-02).

All memory requirements are expressed against this interface - remember / recall /
improve / forget over scope-tagged facts and explicit relationships. The engine
is a configuration choice, not a code dependency of the kernel or fleet: Cognee is
the reference production implementation; ``LocalMemoryEngine`` is the dev/offline
reference. The interface contract REQUIRES that recall and forget honour the
``scopes`` passed by the kernel - the engine's own isolation is defence-in-depth,
never the sole boundary (SEC-40).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class EngineFact:
    """A node the engine stores. ``relates_to`` are explicit edges to other fact
    ids (the graph). ``owner_scope`` is carried so the engine can scope-bound its
    own traversal; the kernel re-checks it regardless."""

    id: str
    owner_scope: str  # user:<id> | department:<name> | org
    kind: str  # entity | relationship | summary | document_chunk
    content: str
    data_class: str = "standard"  # standard | sensitive
    source_kind: str = "verb_result"
    source_ref: str | None = None
    relates_to: list[str] = field(default_factory=list)


@dataclass
class RecallHit:
    """A recalled fact with provenance: the match score, how many hops from a
    query-seed it was reached, and the traversal path (fact ids) that led to it."""

    fact: EngineFact
    score: float
    hops: int = 0
    path: list[str] = field(default_factory=list)


def signal_delta(signal: str) -> float:
    """The recall-weight delta for a feedback signal: negative signals subtract,
    everything else adds (shared by every engine's ``improve``, SEC-41)."""
    return 1.0 if signal not in ("down", "negative", "fail") else -1.0


@runtime_checkable
class MemoryEngine(Protocol):
    async def remember(self, tenant_id: str, facts: list[EngineFact]) -> list[str]:
        """Commit facts/edges; return the engine ids."""
        ...

    async def recall(
        self,
        tenant_id: str,
        query: str,
        *,
        scopes: list[str],
        mode: str = "graph_completion",
        limit: int = 20,
        max_hops: int = 4,
    ) -> list[RecallHit]:
        """Return facts relevant to ``query`` from ``scopes`` only. ``similarity``
        ranks by match; ``graph_completion`` traverses explicit edges up to
        ``max_hops`` WITHOUT crossing into a scope not in ``scopes`` (SEC-40)."""
        ...

    async def improve(self, tenant_id: str, signal: str, target: str) -> int:
        """Reweight from a usage/feedback signal; return the number adjusted. Must
        never change a fact's scope or grant any authority (SEC-41)."""
        ...

    async def forget(
        self,
        tenant_id: str,
        *,
        fact_ids: list[str] | None = None,
        source_ref: str | None = None,
        scopes: list[str] | None = None,
    ) -> list[str]:
        """Remove the target node(s) and their derived edges/facts; return the ids
        actually removed (for verifiable, complete erasure, SEC-44). When ``scopes``
        is given, only facts within those scopes may be removed."""
        ...

    async def health(self) -> str:  # 'ok' | 'degraded' | 'down'
        ...
