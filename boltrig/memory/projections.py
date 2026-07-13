"""Kernel-led memory projection fanout.

The MemoryAdapter commits the canonical fact/erasure through the existing
kernel-governed path. This module mirrors that canonical event into secondary
backends such as Mem0 or Cognee and records per-projection state. Projection
backends are never authority; they are catch-up indexes.
"""

from __future__ import annotations

import inspect
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from boltrig.models import InvocationContext, MemoryProjectionStatus, utcnow

from .engine import EngineFact, RecallHit

_ROW_STATUSES = {
    "remember": {"pending", "written", "failed"},
    "forget": {"pending", "deleted", "delete_failed"},
}
_FINAL_STATUSES = {
    "remember": {"written", "failed"},
    "forget": {"deleted", "delete_failed"},
}


@dataclass(frozen=True)
class ProjectionResult:
    status: str
    projection_ref: str | None = None
    error: str | None = None

    @classmethod
    def written(cls, projection_ref: str | None = None) -> "ProjectionResult":
        return cls("written", projection_ref=projection_ref)

    @classmethod
    def deleted(cls, projection_ref: str | None = None) -> "ProjectionResult":
        return cls("deleted", projection_ref=projection_ref)


@dataclass(frozen=True)
class ProjectionRecallHit:
    fact_id: str
    score: float = 1.0
    content: str | None = None
    projection_ref: str | None = None
    hops: int = 0
    path: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProjectedRecall:
    projection_id: str
    hits: list[RecallHit]
    projection_refs: dict[str, str | None]


class MemoryProjection(Protocol):
    id: str

    async def remember(
        self, tenant_id: str, fact: EngineFact, context: InvocationContext
    ) -> ProjectionResult:
        ...

    async def forget(
        self,
        tenant_id: str,
        *,
        fact_id: str,
        projection_ref: str | None,
        context: InvocationContext,
    ) -> ProjectionResult:
        ...


def _short_error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:500]


def _check_status(operation: str, status: str, *, final: bool = False) -> str:
    allowed = _FINAL_STATUSES if final else _ROW_STATUSES
    if operation not in allowed:
        raise ValueError(f"invalid projection operation {operation!r}")
    if status not in allowed[operation]:
        raise ValueError(f"invalid projection status {status!r} for {operation}")
    return status


def _row(
    *,
    tenant_id: str,
    projection_id: str,
    operation: str,
    status: str,
    fact_id: str | None,
    target: str | None,
    projection_ref: str | None = None,
    error: str | None = None,
    row_id: str | None = None,
) -> MemoryProjectionStatus:
    _check_status(operation, status)
    now = utcnow()
    stable_id = row_id or f"{projection_id}:{operation}:{fact_id or target or uuid.uuid4().hex}"
    return MemoryProjectionStatus(
        id=stable_id,
        tenant_id=tenant_id,
        projection_id=projection_id,
        operation=operation,
        status=status,
        fact_id=fact_id,
        target=target,
        projection_ref=projection_ref,
        error=error,
        created_at=now,
        updated_at=now,
    )


class MemoryProjectionFanout:
    def __init__(
        self,
        store: Any,
        projections: list[MemoryProjection] | None = None,
        *,
        primary_projection_id: str = "mem0",
    ) -> None:
        self._store = store
        self._projections = list(projections or [])
        self._primary_projection_id = primary_projection_id

    def enabled(self) -> bool:
        return bool(self._projections)

    async def remember(
        self, tenant_id: str, fact: EngineFact, context: InvocationContext
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for projection in self._projections:
            row_id = f"{projection.id}:remember:{fact.id}"
            await self._upsert(_row(
                tenant_id=tenant_id,
                projection_id=projection.id,
                operation="remember",
                status="pending",
                fact_id=fact.id,
                target=None,
                row_id=row_id,
            ))
            try:
                result = await projection.remember(tenant_id, fact, context)
                status = _check_status("remember", result.status, final=True)
                final = _row(
                    tenant_id=tenant_id,
                    projection_id=projection.id,
                    operation="remember",
                    status=status,
                    fact_id=fact.id,
                    target=None,
                    projection_ref=result.projection_ref,
                    error=result.error,
                    row_id=row_id,
                )
            except Exception as exc:
                final = _row(
                    tenant_id=tenant_id,
                    projection_id=projection.id,
                    operation="remember",
                    status="failed",
                    fact_id=fact.id,
                    target=None,
                    error=_short_error(exc),
                    row_id=row_id,
                )
            await self._upsert(final)
            rows.append(_public(final))
        return rows

    async def forget(
        self, tenant_id: str, fact_ids: list[str], context: InvocationContext
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for fact_id in fact_ids:
            previous = {
                row.projection_id: row
                for row in await self._list(tenant_id, fact_id=fact_id, limit=100)
                if row.operation == "remember"
            }
            for projection in self._projections:
                row_id = f"{projection.id}:forget:{fact_id}"
                prior = previous.get(projection.id)
                await self._upsert(_row(
                    tenant_id=tenant_id,
                    projection_id=projection.id,
                    operation="forget",
                    status="pending",
                    fact_id=fact_id,
                    target=fact_id,
                    projection_ref=getattr(prior, "projection_ref", None),
                    row_id=row_id,
                ))
                try:
                    result = await projection.forget(
                        tenant_id,
                        fact_id=fact_id,
                        projection_ref=getattr(prior, "projection_ref", None),
                        context=context,
                    )
                    status = _check_status("forget", result.status, final=True)
                    final = _row(
                        tenant_id=tenant_id,
                        projection_id=projection.id,
                        operation="forget",
                        status=status,
                        fact_id=fact_id,
                        target=fact_id,
                        projection_ref=result.projection_ref or getattr(prior, "projection_ref", None),
                        error=result.error,
                        row_id=row_id,
                    )
                except Exception as exc:
                    final = _row(
                        tenant_id=tenant_id,
                        projection_id=projection.id,
                        operation="forget",
                        status="delete_failed",
                        fact_id=fact_id,
                        target=fact_id,
                        projection_ref=getattr(prior, "projection_ref", None),
                        error=_short_error(exc),
                        row_id=row_id,
                    )
                await self._upsert(final)
                rows.append(_public(final))
        return rows

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
    ) -> ProjectedRecall | None:
        projection = self._primary_projection()
        recaller = getattr(projection, "recall", None) if projection is not None else None
        if projection is None or not callable(recaller):
            return None
        try:
            raw_hits = await recaller(
                tenant_id,
                query,
                scopes=scopes,
                mode=mode,
                limit=limit,
                max_hops=max_hops,
                context=context,
            )
        except Exception:
            return None

        allowed = set(scopes)
        hits: list[RecallHit] = []
        refs: dict[str, str | None] = {}
        for raw in raw_hits[:limit]:
            fact = await self._get_fact(tenant_id, raw.fact_id)
            if fact is None or fact.owner_scope not in allowed:
                continue
            content = raw.content if raw.content is not None else fact.content
            ef = EngineFact(
                id=fact.id,
                owner_scope=fact.owner_scope,
                kind=fact.kind,
                content=content,
                data_class=fact.data_class,
                source_kind=fact.source_kind,
                source_ref=fact.source_ref,
            )
            hits.append(RecallHit(
                fact=ef,
                score=raw.score,
                hops=raw.hops,
                path=raw.path or [fact.id],
            ))
            refs[fact.id] = raw.projection_ref
            if len(hits) >= limit:
                break
        return ProjectedRecall(projection.id, hits, refs)

    async def _upsert(self, status: MemoryProjectionStatus) -> None:
        result = self._store.upsert_memory_projection_status(status)
        if inspect.isawaitable(result):
            await result

    async def _list(self, tenant_id: str, *, fact_id: str, limit: int):
        result = self._store.list_memory_projection_statuses(
            tenant_id, fact_id=fact_id, limit=limit
        )
        if inspect.isawaitable(result):
            return await result
        return result

    async def _get_fact(self, tenant_id: str, fact_id: str):
        result = self._store.get_memory_fact(tenant_id, fact_id)
        if inspect.isawaitable(result):
            return await result
        return result

    def _primary_projection(self):
        for projection in self._projections:
            if projection.id == self._primary_projection_id:
                return projection
        return None


def _public(row: MemoryProjectionStatus) -> dict[str, Any]:
    out: dict[str, Any] = {
        "projection_id": row.projection_id,
        "operation": row.operation,
        "status": row.status,
        "fact_id": row.fact_id,
    }
    if row.projection_ref:
        out["projection_ref"] = row.projection_ref
    if row.error:
        out["error"] = row.error
    return out
