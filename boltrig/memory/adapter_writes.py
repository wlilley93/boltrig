"""Governed memory ingestion helpers shared by the built-in adapter."""

from __future__ import annotations

import uuid

from boltrig.adapters.base import AdapterError, ErrorClass, Result
from boltrig.kernel.pii import contains_secret
from boltrig.models import (
    GrantMissing,
    InvocationContext,
    MemoryFact,
    MemoryIngestion,
    SensitiveDataMisrouted,
)
from boltrig.store.base import MAX_INGEST_ITEMS

from .engine import EngineFact

_INJECTION_MARKERS: tuple[str, ...] = (
    "ignore previous",
    "ignore all previous",
    "ignore the above",
    "disregard previous",
    "disregard all",
    "system prompt",
    "you are now",
    "</system>",
    "<script",
    "javascript:",
    "eval(",
    "drop table",
    "rm -rf",
    "begin pgp",
    ";base64,",
    "new instructions:",
    "override your",
)


def screen_content(text: str) -> str | None:
    """Return a reason if content resembles an injection or malware payload."""
    low = (text or "").lower()
    for marker in _INJECTION_MARKERS:
        if marker in low:
            return f"possible injection/malware marker: {marker!r}"
    return None


def permitted_scopes(context: InvocationContext) -> list[str]:
    """Resolve caller-owned memory scopes, failing closed to user plus org."""
    scopes = (context.extra or {}).get("memory_scopes")
    if scopes:
        return [str(scope) for scope in scopes]
    owner = context.on_behalf_of or context.actor
    return [f"user:{owner}", "org"]


def owner_default(context: InvocationContext) -> str:
    owner = context.on_behalf_of or context.actor
    return f"user:{owner}"


class MemoryWriteMixin:
    async def _remember(self, params, context, scopes) -> Result:
        tenant = context.tenant_id
        content = params.get("content", "")
        owner_scope = params.get("owner_scope") or owner_default(context)
        refused = await self._refuse_unsafe_content(content, owner_scope, context, scopes)
        if refused is not None:
            return refused
        data_class = params.get("data_class", "standard")
        if data_class == "sensitive" and self._sensitive_endpoint not in self._local_endpoints:
            await self._write_audit(
                context,
                "memory.residency.blocked",
                {"endpoint": self._sensitive_endpoint},
                status="denied",
            )
            raise SensitiveDataMisrouted(
                f"sensitive memory cannot use non-local endpoint {self._sensitive_endpoint}"
            )
        relates = await self._permitted_edges(tenant, params.get("relates_to") or [], scopes)
        fact = _engine_fact(params, owner_scope, content, data_class, relates)
        ledger_error = await self._persist_memory_fact(tenant, fact)
        if ledger_error is not None:
            return ledger_error
        try:
            await self._engine.remember(tenant, [fact])
        except Exception as exc:
            await self._store.delete_memory_fact(tenant, fact.id)
            return Result.failure(
                AdapterError(
                    ErrorClass.UNAVAILABLE,
                    f"memory engine write failed: {type(exc).__name__}",
                    retryable=True,
                )
            )
        projections = []
        if self._projections is not None:
            projections = await self._projections.remember(tenant, fact, context)
        return Result.success(
            {
                "fact_ids": [fact.id],
                "owner_scope": owner_scope,
                "projections": projections,
            }
        )

    async def _refuse_unsafe_content(self, content, owner_scope, context, scopes):
        if owner_scope not in set(scopes):
            await self._write_audit(
                context,
                "memory.ingest.denied",
                {"owner_scope": owner_scope},
                status="denied",
            )
            raise GrantMissing(f"cannot write memory to scope {owner_scope}")
        reason = screen_content(content)
        if reason:
            await self._write_audit(
                context,
                "memory.ingest.rejected",
                {"reason": reason, "owner_scope": owner_scope},
                status="denied",
            )
            return Result.failure(AdapterError(ErrorClass.INVALID, f"content rejected: {reason}"))
        secret_kind = contains_secret(content)
        if secret_kind:
            await self._write_audit(
                context,
                "memory.ingest.secret_blocked",
                {"secret_kind": secret_kind, "owner_scope": owner_scope},
                status="denied",
            )
            return Result.failure(
                AdapterError(
                    ErrorClass.INVALID,
                    f"content contains a secret ({secret_kind}); memory ingestion blocked",
                )
            )
        return None

    async def _permitted_edges(self, tenant, relates_to, scopes):
        relates = [str(ref) for ref in relates_to]
        if self._cross_scope_edges != "forbidden":
            return relates
        return [ref for ref in relates if await self._fact_in_scope(tenant, ref, scopes)]

    async def _persist_memory_fact(self, tenant, fact):
        try:
            await self._store.add_memory_fact(
                MemoryFact(
                    id=fact.id,
                    tenant_id=tenant,
                    owner_scope=fact.owner_scope,
                    engine_ref=fact.id,
                    kind=fact.kind,
                    source_kind=fact.source_kind,
                    source_ref=fact.source_ref,
                    data_class=fact.data_class,
                    content=fact.content[:200],
                )
            )
        except Exception as exc:
            return Result.failure(
                AdapterError(
                    ErrorClass.INTERNAL,
                    f"memory ledger write failed: {type(exc).__name__}",
                )
            )
        return None

    async def _ingest(self, params, context, scopes) -> Result:
        tenant = context.tenant_id
        source_kind = str(params.get("source_kind") or "document")
        source_ref = str(params.get("source_ref") or "")
        owner_scope = str(params.get("owner_scope") or owner_default(context))
        if owner_scope not in set(scopes):
            raise GrantMissing(f"cannot write memory to scope {owner_scope}")
        items = await _source_items(
            self._store, tenant, source_kind, source_ref, params.get("items")
        )
        if len(items) > MAX_INGEST_ITEMS:
            return Result.failure(
                AdapterError(
                    ErrorClass.INVALID,
                    f"too many items (max {MAX_INGEST_ITEMS})",
                )
            )
        ingestion = MemoryIngestion(
            id=uuid.uuid4().hex,
            tenant_id=tenant,
            source_kind=source_kind,
            source_ref=source_ref,
            owner_scope=owner_scope,
            status="screening",
        )
        await self._store.add_memory_ingestion(ingestion)
        clean = [text for text in items if screen_content(text) is None]
        rejected = len(items) - len(clean)
        ingestion.screened = True
        if not clean:
            return await self._finish_empty_ingestion(ingestion, rejected)
        ingestion.status = "cognifying"
        await self._store.update_memory_ingestion(ingestion)
        added, failed = await self._remember_ingestion_items(
            clean, owner_scope, source_kind, source_ref, context, scopes
        )
        ingestion.facts_added = added
        ingestion.status = "done"
        ingestion.detail = {
            "rejected_items": rejected,
            "failed_items": failed,
            "execution": "kernel_batch",
        }
        await self._store.update_memory_ingestion(ingestion)
        return _ingestion_result(ingestion)

    async def _finish_empty_ingestion(self, ingestion, rejected):
        ingestion.screened = True
        ingestion.status = "rejected"
        ingestion.detail = {"rejected_items": rejected, "failed_items": 0}
        await self._store.update_memory_ingestion(ingestion)
        return _ingestion_result(ingestion)

    async def _remember_ingestion_items(
        self, clean, owner_scope, source_kind, source_ref, context, scopes
    ):
        added = failed = 0
        for text in clean:
            result = await self._remember(
                {
                    "content": text,
                    "owner_scope": owner_scope,
                    "kind": "document_chunk",
                    "source_kind": source_kind,
                    "source_ref": source_ref,
                },
                context,
                scopes,
            )
            if result.ok:
                added += len(result.output.get("fact_ids", []))
            else:
                failed += 1
        return added, failed


def _engine_fact(params, owner_scope, content, data_class, relates):
    return EngineFact(
        id=uuid.uuid4().hex,
        owner_scope=owner_scope,
        kind=params.get("kind", "entity"),
        content=content,
        data_class=data_class,
        source_kind=params.get("source_kind", "verb_result"),
        source_ref=params.get("source_ref"),
        relates_to=relates,
    )


async def _source_items(store, tenant, source_kind, source_ref, raw_items):
    if source_kind == "conversation":
        messages = await store.list_messages(tenant, source_ref)
        return [str(message.content) for message in messages if getattr(message, "content", None)]
    return [str(item) for item in (raw_items or [])]


def _ingestion_result(ingestion):
    return Result.success(
        {
            "id": ingestion.id,
            "ingestion_status": ingestion.status,
            "facts_added": ingestion.facts_added,
            "screened": True,
        }
    )


__all__ = ["MemoryWriteMixin", "permitted_scopes", "screen_content"]
