"""Cognee adoption seam (MEM-ENG-03).

Cognee is the reference production Memory Engine: self-hostable, Postgres-capable,
permissively licensed, with provider-agnostic embedding/extraction (so sensitive
data can use a local endpoint, SEC-43) and built-in tenant isolation. It is
ADOPTED behind ``MemoryEngine``, not built here. This module is the single place
that touches the ``cognee`` package; it lazy-imports so the rest of Boltrig is
import-safe and offline-safe without it, and raises a clear error until the
adoption is wired and validated against the MEM-ENG-04 selection criteria.
"""

from __future__ import annotations

from typing import Any

from .engine import EngineFact, RecallHit


def _require_cognee() -> Any:
    try:
        import cognee  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised only without cognee
        raise RuntimeError(
            "CogneeEngine requires the 'cognee' package (pip install cognee). "
            "Memory engines are ADOPTED, not built (MEM-ENG-01); validate Cognee "
            "against the MEM-ENG-04 criteria before enabling it in production."
        ) from exc
    return cognee


class CogneeEngine:
    """The adopted production engine. Construction is cheap (no import); the cognee
    library is required only when an operation runs, so config can be validated and
    the offline suite stays green without the package installed."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = dict(config or {})

    async def remember(self, tenant_id: str, facts: list[EngineFact]) -> list[str]:
        _require_cognee()
        raise NotImplementedError(
            "CogneeEngine.remember: wire cognee.add() + cognee.cognify() here, scoping "
            "the dataset by owner_scope and routing sensitive extraction/embedding to "
            "the local endpoint (SEC-43)."
        )

    async def recall(self, tenant_id, query, *, scopes, mode="graph_completion",
                     limit=20, max_hops=4) -> list[RecallHit]:
        _require_cognee()
        raise NotImplementedError(
            "CogneeEngine.recall: wire cognee.search() bounded to the given scopes; "
            "the kernel re-checks scope on the returned facts (SEC-40)."
        )

    async def improve(self, tenant_id: str, signal: str, target: str) -> int:
        _require_cognee()
        raise NotImplementedError("CogneeEngine.improve: wire cognee feedback/memify here.")

    async def forget(self, tenant_id, *, fact_ids=None, source_ref=None, scopes=None) -> list[str]:
        _require_cognee()
        raise NotImplementedError(
            "CogneeEngine.forget: wire cognee.prune / node deletion incl derived edges, "
            "and return the removed ids for verifiable erasure (SEC-44)."
        )

    async def health(self) -> str:
        return "down"  # not wired until the adoption is completed + validated
