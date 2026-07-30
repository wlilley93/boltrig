"""The MemoryAdapter: memory.* verbs behind the kernel chokepoint, and the
kernel-side isolation boundary (Epic MEM, SEC-40..45).

The adapter fronts whichever ``MemoryEngine`` is configured. Because it is a normal
adapter, every memory operation runs the unchanged dispatch sequence - grant check
+ audit + schema validation (NFR-MEM-05). On top of that the adapter enforces the
memory-specific controls the kernel, not the engine, owns:

  * owner-scope at ingestion AND retrieval - the engine is given the caller's
    permitted scopes and the returned facts are re-filtered to them, so a hostile
    cross-scope recall (including multi-hop) cannot reach an out-of-scope fact
    (SEC-40);
  * recalled content is returned as data, never executed, and never changes the
    caller's authority (SEC-41);
  * content is screened for injection/malware before it becomes memory (SEC-42);
  * sensitive memory must use a local endpoint - a misroute is blocked + audited
    (SEC-43);
  * forgetting removes the node and its derived edges/facts and is ledgered +
    audited (SEC-44);
  * recall is least-privilege and audited - query/scope/count, never contents
    (SEC-45).
"""

from __future__ import annotations

import hashlib
import json
import uuid

from boltrig.adapters.base import AdapterError, Credential, ErrorClass, Result, VerbSpec
from boltrig.models import (
    ActionType,
    AuditEvent,
    GrantMissing,
    InvocationContext,
    MemoryErasure,
    utcnow,
)

from .adapter_specs import memory_verb_specs
from .adapter_writes import (
    MemoryWriteMixin,
    permitted_scopes,
    screen_content,
)


class MemoryAdapter(MemoryWriteMixin):
    id = "memory"
    version = "1.0.0"
    runtime = "script"
    source = "builtin"

    def __init__(
        self,
        engine,
        store,
        *,
        audit=None,
        sensitive_endpoint: str = "local-sensitive",
        local_endpoints: set[str] | None = None,
        cross_scope_edges: str = "forbidden",
        max_hops: int = 4,
        max_results: int = 20,
        projections=None,
    ) -> None:
        self._engine = engine
        self._store = store
        self._audit = audit
        self._sensitive_endpoint = sensitive_endpoint
        self._local_endpoints = local_endpoints or {sensitive_endpoint}
        self._cross_scope_edges = cross_scope_edges
        self._max_hops = max_hops
        self._max_results = max_results
        self._projections = projections

    def describe(self) -> list[VerbSpec]:
        return memory_verb_specs()

    async def execute(
        self, verb: str, params: dict, credential: Credential | None, context: InvocationContext
    ) -> Result:
        scopes = permitted_scopes(context)
        if verb == "memory.remember":
            return await self._remember(params, context, scopes)
        if verb == "memory.ingest":
            return await self._ingest(params, context, scopes)
        if verb == "memory.recall":
            return await self._recall(params, context, scopes)
        if verb == "memory.improve":
            return await self._improve(params, context, scopes)
        if verb == "memory.forget":
            if not params.get("target") and not params.get("source_ref"):
                return Result.failure(
                    AdapterError(
                        ErrorClass.INVALID,
                        "memory.forget requires a 'target' or 'source_ref' - an empty "
                        "erasure must never be a silent no-op",
                    )
                )
            return await self._forget(params, context, scopes)
        return Result.failure(AdapterError(ErrorClass.INVALID, f"unknown verb {verb}"))

    async def approval_context(
        self, verb: str, params: dict, context: InvocationContext
    ) -> dict | None:
        """Bind conversation ingestion to the transcript snapshot being approved."""

        if verb != "memory.ingest" or params.get("source_kind") != "conversation":
            return None
        messages = await self._store.list_messages(
            context.tenant_id, str(params.get("source_ref") or "")
        )
        contents = [
            str(message.content) for message in messages if getattr(message, "content", None)
        ]
        digest = hashlib.sha256(
            json.dumps(
                contents,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return {
            "source_kind": "conversation",
            "source_ref": str(params.get("source_ref") or ""),
            "message_count": len(contents),
            "content_digest": digest,
        }

    async def health(self) -> str:
        return await self._engine.health()

    # --- audit helper (memory-governance events, contents never logged) ---
    async def _write_audit(self, context, verb, detail, status="ok") -> None:
        if self._audit is None:
            return
        await self._audit.write(
            AuditEvent(
                tenant_id=context.tenant_id,
                ts=utcnow(),
                actor=context.actor,
                actor_tier=context.actor_tier,
                action_type=ActionType.TOOL_CALL,
                verb=verb,
                status=status,
                on_behalf_of=context.on_behalf_of,
                run_id=context.run_id,
                workspace_id=context.workspace_id,
                detail=detail,
            )
        )

    async def _fact_in_scope(self, tenant_id, fact_id, scopes) -> bool:
        f = await self._store.get_memory_fact(tenant_id, fact_id)
        return f is not None and f.owner_scope in set(scopes)

    # --- memory.recall (retrieval boundary: scope-filter + least-priv audit) ---
    async def _recall(self, params, context, scopes) -> Result:
        tenant = context.tenant_id
        requested_scope = params.get("owner_scope")
        if requested_scope:
            if requested_scope not in set(scopes):
                raise GrantMissing(f"cannot recall memory from scope {requested_scope}")
            scopes = [requested_scope]
        query = params.get("query", "")
        mode = params.get("mode", "graph_completion")
        limit = min(int(params.get("limit", self._max_results)), self._max_results)
        source = "engine"
        projection_refs: dict[str, str | None] = {}
        projected = None
        if self._projections is not None:
            projected = await self._projections.recall(
                tenant,
                query,
                scopes=scopes,
                mode=mode,
                limit=limit,
                max_hops=self._max_hops,
                context=context,
            )
        if projected is not None:
            hits = projected.hits
            source = projected.projection_id
            projection_refs = projected.projection_refs
        else:
            hits = await self._engine.recall(
                tenant, query, scopes=scopes, mode=mode, limit=limit, max_hops=self._max_hops
            )
        # SEC-40 defence-in-depth: re-filter to permitted scopes even if the engine
        # returned anything broader.
        allowed = set(scopes)
        facts = [
            {
                "id": h.fact.id,
                "owner_scope": h.fact.owner_scope,
                "kind": h.fact.kind,
                "content": h.fact.content,
                "data_class": h.fact.data_class,
                "provenance": {
                    "source_kind": h.fact.source_kind,
                    "source_ref": h.fact.source_ref,
                    "hops": h.hops,
                    "path": h.path,
                },
                "projection": {
                    "source": source,
                    "ref": projection_refs.get(h.fact.id),
                    "authority": "kernel_ledger",
                },
            }
            for h in hits
            if h.fact.owner_scope in allowed
        ]
        # SEC-45: audit the query/scope/count, never the contents.
        await self._write_audit(
            context,
            "memory.recall",
            {"query": query, "mode": mode, "scopes": scopes, "count": len(facts)},
        )
        return Result.success({"facts": facts, "count": len(facts), "projection_source": source})

    # --- memory.improve (reweight; cannot change scope or grant authority) ---
    async def _improve(self, params, context, scopes) -> Result:
        target = params.get("target", "")
        if not await self._fact_in_scope(context.tenant_id, target, scopes):
            await self._write_audit(
                context,
                "memory.improve.denied",
                {"target": target},
                status="denied",
            )
            raise GrantMissing("memory fact is not visible to this caller")
        adjusted = await self._engine.improve(context.tenant_id, params.get("signal", ""), target)
        await self._write_audit(
            context,
            "memory.improve",
            {"target": target, "adjusted": adjusted},
        )
        return Result.success({"adjusted": adjusted})

    # --- memory.forget (complete, ledgered, audited erasure) ---
    async def _forget(self, params, context, scopes) -> Result:
        tenant = context.tenant_id
        target = params.get("target")
        source_ref = params.get("source_ref")
        removed = await self._engine.forget(
            tenant, fact_ids=[target] if target else None, source_ref=source_ref, scopes=scopes
        )
        for fid in removed:
            await self._store.delete_memory_fact(tenant, fid)
        erasure = MemoryErasure(
            id=uuid.uuid4().hex,
            tenant_id=tenant,
            requested_by=context.actor,
            target=str(target or source_ref or ""),
            scope=",".join(scopes),
            engine_confirmed=True,
            transcript_handled=bool(source_ref),
            facts_removed=len(removed),
            completed_at=utcnow(),
        )
        await self._store.add_memory_erasure(erasure)
        await self._write_audit(
            context,
            "memory.forget",
            {"target": erasure.target, "facts_removed": len(removed), "engine_confirmed": True},
        )
        projections = []
        if self._projections is not None and removed:
            projections = await self._projections.forget(tenant, removed, context)
        return Result.success(
            {
                "erasure_id": erasure.id,
                "removed": removed,
                "facts_removed": len(removed),
                "engine_confirmed": True,
                "transcript_handled": erasure.transcript_handled,
                "projections": projections,
            }
        )


def build_memory_adapter(
    engine, store, *, audit=None, config: dict | None = None, projections=None
) -> MemoryAdapter:
    """Construct a MemoryAdapter from a manifest ``memory`` config block."""
    cfg = config or {}
    sensitive = cfg.get("embedding_endpoint", "local-sensitive")
    local = set(
        cfg.get("local_endpoints") or [sensitive, cfg.get("extraction_endpoint", sensitive)]
    )
    retrieval = cfg.get("retrieval", {}) or {}
    return MemoryAdapter(
        engine,
        store,
        audit=audit,
        sensitive_endpoint=sensitive,
        local_endpoints=local,
        cross_scope_edges=cfg.get("cross_scope_edges", "forbidden"),
        max_hops=int(retrieval.get("max_hops", 4)),
        max_results=int(retrieval.get("max_results", 20)),
        projections=projections,
    )


__all__ = [
    "MemoryAdapter",
    "build_memory_adapter",
    "permitted_scopes",
    "screen_content",
]
