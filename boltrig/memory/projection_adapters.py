"""Concrete memory projection adapters for Boltrig v2.

The kernel ledger stays authoritative. These adapters only mirror governed memory
facts into external recall/enrichment products and expose labelled recall hits.
"""

from __future__ import annotations

import inspect
import json
import os
from typing import Any

from boltrig.config.environment import is_truthy
from boltrig.models import InvocationContext

from .cognee import CogneeEngine
from .engine import EngineFact
from .projections import MemoryProjectionFanout, ProjectionRecallHit, ProjectionResult
from .projection_queue import QueuedMemoryProjectionFanout, is_queued_projection_mode


def _entity_id(tenant_id: str, owner_scope: str) -> str:
    return f"{tenant_id}:{owner_scope}"


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return is_truthy(str(value))


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


async def _call(client: Any, method: str, *args, **kwargs):
    return await _maybe_await(getattr(client, method)(*args, **kwargs))


def _results(payload: Any) -> list[Any]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("results", "memories", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        return [payload]
    return [payload]


def _item_id(item: Any) -> str | None:
    if isinstance(item, dict):
        return item.get("id") or item.get("memory_id") or item.get("event_id")
    return getattr(item, "id", None) or getattr(item, "memory_id", None)


def _item_metadata(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item.get("metadata") or {})
    return dict(getattr(item, "metadata", None) or {})


def _item_content(item: Any) -> str | None:
    if isinstance(item, dict):
        value = item.get("memory") or item.get("text") or item.get("content")
        return str(value) if value is not None else None
    value = getattr(item, "memory", None) or getattr(item, "text", None)
    return str(value) if value is not None else None


def _item_score(item: Any) -> float:
    value = item.get("score") if isinstance(item, dict) else getattr(item, "score", None)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 1.0


def _pack_ref(*, entity: str, memory_id: str | None = None, event_id: str | None = None) -> str:
    return json.dumps(
        {"entity": entity, "memory_id": memory_id, "event_id": event_id},
        separators=(",", ":"),
        sort_keys=True,
    )


def _unpack_ref(ref: str | None) -> dict[str, str | None]:
    if not ref:
        return {}
    try:
        data = json.loads(ref)
    except json.JSONDecodeError:
        return {"memory_id": ref}
    return data if isinstance(data, dict) else {"memory_id": ref}


class Mem0Projection:
    id = "mem0"

    def __init__(self, config: dict[str, Any] | None = None, *, client: Any = None) -> None:
        self._config = dict(config or {})
        self._client = client
        self._infer = _as_bool(self._config.get("infer"))
        self._threshold = self._config.get("threshold")
        self._rerank = _as_bool(self._config.get("rerank"))

    def _ready(self):
        if self._client is not None:
            return self._client
        mode = str(self._config.get("mode", "platform")).lower()
        if mode == "oss":
            from mem0 import Memory

            self._client = Memory()
            return self._client
        api_key = self._config.get("api_key") or os.environ.get("MEM0_API_KEY")
        if api_key:
            os.environ.setdefault("MEM0_API_KEY", str(api_key))
        try:
            from mem0 import AsyncMemoryClient

            self._client = AsyncMemoryClient(api_key=api_key) if api_key else AsyncMemoryClient()
        except (ImportError, TypeError):
            from mem0 import MemoryClient

            self._client = MemoryClient(api_key=api_key) if api_key else MemoryClient()
        return self._client

    async def remember(
        self, tenant_id: str, fact: EngineFact, context: InvocationContext
    ) -> ProjectionResult:
        entity = _entity_id(tenant_id, fact.owner_scope)
        metadata = {
            "tenant_id": tenant_id,
            "owner_scope": fact.owner_scope,
            "fact_id": fact.id,
            "source_kind": fact.source_kind,
            "source_ref": fact.source_ref,
            "boltrig_authority": "kernel_ledger",
        }
        payload = await _call(
            self._ready(),
            "add",
            messages=[{"role": "user", "content": fact.content}],
            user_id=entity,
            metadata=metadata,
            infer=self._infer,
        )
        if isinstance(payload, dict) and str(payload.get("status", "")).upper() == "FAILED":
            return ProjectionResult("failed", error=str(payload.get("message") or payload))
        ref = _pack_ref(
            entity=entity,
            memory_id=_extract_first_id(payload, exclude_event=True),
            event_id=_extract_event_id(payload),
        )
        return ProjectionResult.written(ref)

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
        hits: list[ProjectionRecallHit] = []
        for scope in scopes:
            entity = _entity_id(tenant_id, scope)
            items = await self._search(entity, query, max(1, limit - len(hits)))
            for item in items:
                meta = _item_metadata(item)
                if meta.get("tenant_id") != tenant_id or meta.get("owner_scope") != scope:
                    continue
                fact_id = meta.get("fact_id")
                memory_id = _item_id(item)
                if not fact_id:
                    continue
                hits.append(ProjectionRecallHit(
                    fact_id=str(fact_id),
                    score=_item_score(item),
                    content=_item_content(item),
                    projection_ref=_pack_ref(entity=entity, memory_id=memory_id),
                ))
                if len(hits) >= limit:
                    return hits
        return hits

    async def forget(
        self,
        tenant_id: str,
        *,
        fact_id: str,
        projection_ref: str | None,
        context: InvocationContext,
    ) -> ProjectionResult:
        ref = _unpack_ref(projection_ref)
        memory_ids = [ref["memory_id"]] if ref.get("memory_id") else []
        if not memory_ids and ref.get("entity"):
            memory_ids = await self._find_memory_ids(str(ref["entity"]), fact_id)
        for memory_id in dict.fromkeys(memory_ids):
            await _call(self._ready(), "delete", memory_id=memory_id)
        return ProjectionResult.deleted(projection_ref)

    async def _search(self, entity: str, query: str, limit: int) -> list[Any]:
        client = self._ready()
        kwargs = {"filters": {"user_id": entity}}
        if query.strip():
            kwargs["top_k"] = limit
            if self._threshold is not None:
                kwargs["threshold"] = float(self._threshold)
            if self._rerank:
                kwargs["rerank"] = True
            return _results(await _call(client, "search", query, **kwargs))
        if hasattr(client, "get_all"):
            return _results(await _call(client, "get_all", page_size=limit, **kwargs))
        return []

    async def _find_memory_ids(self, entity: str, fact_id: str) -> list[str]:
        if not hasattr(self._ready(), "get_all"):
            return []
        filters = {"AND": [{"user_id": entity}, {"fact_id": fact_id}]}
        payload = await _call(self._ready(), "get_all", filters=filters, page_size=20)
        return [mid for item in _results(payload) if (mid := _item_id(item))]


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


def _extract_first_id(payload: Any, *, exclude_event: bool = False) -> str | None:
    if isinstance(payload, dict):
        keys = ("id", "memory_id") if exclude_event else ("id", "memory_id", "event_id")
        for key in keys:
            if payload.get(key):
                return str(payload[key])
    for item in _results(payload):
        if mid := _item_id(item):
            return str(mid)
    return None


def _extract_event_id(payload: Any) -> str | None:
    return str(payload["event_id"]) if isinstance(payload, dict) and payload.get("event_id") else None


def build_memory_projection_fanout(store: Any, memory_cfg: dict[str, Any] | None):
    cfg = dict(memory_cfg or {})
    projections = []
    for entry in cfg.get("projections") or []:
        if not isinstance(entry, dict) or not _as_bool(entry.get("enabled")):
            continue
        merged = {**cfg, **(entry.get("config") or {}), **entry}
        if entry.get("id") == "mem0":
            projections.append(Mem0Projection(merged))
        elif entry.get("id") == "cognee":
            projections.append(CogneeProjection(merged))
    if not projections:
        return None
    fanout_cfg = cfg.get("fanout") if isinstance(cfg.get("fanout"), dict) else {}
    # fanout.retry_failed, READ since 2026-07-31 (task #40). Default TRUE: the
    # field's name promises retry and the shipped example says `true`, so absence
    # keeps the promise. False means fail fast, honestly, in both modes.
    retry_failed = _as_bool(fanout_cfg.get("retry_failed", True))
    primary = str(cfg.get("primary_projection") or "mem0")
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
