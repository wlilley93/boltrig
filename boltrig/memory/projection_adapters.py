"""Concrete memory projection adapters for Boltrig v2.

The kernel ledger stays authoritative. These adapters only mirror governed memory
facts into external recall/enrichment products and expose labelled recall hits.
"""

from __future__ import annotations

from typing import Any

from boltrig.config.environment import is_truthy
from boltrig.models import InvocationContext

from .cognee import CogneeEngine
from .engine import EngineFact
from .projections import MemoryProjectionFanout, ProjectionRecallHit, ProjectionResult
from .projection_queue import QueuedMemoryProjectionFanout, is_queued_projection_mode


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return is_truthy(str(value))


class CogneeProjection:
    id = "cognee"

    def __init__(self, config: dict[str, Any] | None = None, *, engine: CogneeEngine | None = None):
        self._engine = engine or CogneeEngine(config)

    async def remember(
        self, tenant_id: str, fact: EngineFact, context: InvocationContext
    ) -> ProjectionResult:
        await self._engine.remember(tenant_id, [fact])
        return ProjectionResult.written(f"cognee:{fact.id}")

    async def recall(
        self,
        tenant_id: str,
        query: str,
        *,
        scopes: list[str],
        mode: str,
        limit: int,
        max_hops: int,
        context: InvocationContext,
    ) -> list[ProjectionRecallHit]:
        hits = await self._engine.recall(
            tenant_id, query, scopes=scopes, mode=mode, limit=limit, max_hops=max_hops)
        return [
            ProjectionRecallHit(
                fact_id=h.fact.id,
                score=h.score,
                content=h.fact.content,
                projection_ref=f"cognee:{h.fact.id}",
                hops=h.hops,
                path=h.path,
            )
            for h in hits
        ]

    async def forget(
        self,
        tenant_id: str,
        *,
        fact_id: str,
        projection_ref: str | None,
        context: InvocationContext,
    ) -> ProjectionResult:
        await self._engine.forget(tenant_id, fact_ids=[fact_id], scopes=None)
        return ProjectionResult.deleted(projection_ref or f"cognee:{fact_id}")


def build_memory_projection_fanout(store: Any, memory_cfg: dict[str, Any] | None):
    cfg = dict(memory_cfg or {})
    projections = []
    for entry in cfg.get("projections") or []:
        if not isinstance(entry, dict) or not _as_bool(entry.get("enabled")):
            continue
        merged = {**cfg, **(entry.get("config") or {}), **entry}
        if entry.get("id") == "cognee":
            projections.append(CogneeProjection(merged))
    if not projections:
        return None
    fanout_cfg = cfg.get("fanout") if isinstance(cfg.get("fanout"), dict) else {}
    # fanout.retry_failed, READ since 2026-07-31 (task #40). Default TRUE: the
    # field's name promises retry and the shipped example says `true`, so absence
    # keeps the promise. False means fail fast, honestly, in both modes.
    retry_failed = _as_bool(fanout_cfg.get("retry_failed", True))
    primary = str(cfg.get("primary_projection") or "cognee")
    if is_queued_projection_mode(fanout_cfg.get("execution")):
        return QueuedMemoryProjectionFanout(
            store,
            projections,
            primary_projection_id=primary,
            # False collapses the queued retry budget to a single attempt - the
            # same fact the inline path records as max_operation_attempts=1.
            **({} if retry_failed else {"max_operation_attempts": 1}),
        )
    return MemoryProjectionFanout(
        store,
        projections,
        primary_projection_id=primary,
        retry_failed=retry_failed,
    )
