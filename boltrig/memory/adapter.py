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

import uuid

from boltrig.adapters.base import AdapterError, Credential, ErrorClass, Result, VerbSpec
from boltrig.models import (
    ActionType,
    AuditEvent,
    GrantMissing,
    InvocationContext,
    MemoryErasure,
    MemoryFact,
    SensitiveDataMisrouted,
    utcnow,
)

from boltrig.kernel.pii import contains_secret

from .engine import EngineFact

# Markers that flag content as a possible prompt-injection / malware payload. A
# match means the content is refused at ingestion (SEC-42) - injected instructions
# never persist into the graph.
_INJECTION_MARKERS: tuple[str, ...] = (
    "ignore previous", "ignore all previous", "ignore the above", "disregard previous",
    "disregard all", "system prompt", "you are now", "</system>", "<script",
    "javascript:", "eval(", "drop table", "rm -rf", "begin pgp", ";base64,",
    "new instructions:", "override your",
)

_OBJ: dict = {"type": "object"}


def screen_content(text: str) -> str | None:
    """Return a reason if the content looks like an injection/malware payload (SEC-42)."""
    low = (text or "").lower()
    for marker in _INJECTION_MARKERS:
        if marker in low:
            return f"possible injection/malware marker: {marker!r}"
    return None


def permitted_scopes(context: InvocationContext) -> list[str]:
    """The owner-scopes this caller may read/write. Supplied by the boundary in
    context.extra['memory_scopes']; otherwise the fail-closed default of the
    caller's own user scope plus the org scope (never another user/department)."""
    extra = context.extra or {}
    scopes = extra.get("memory_scopes")
    if scopes:
        return [str(s) for s in scopes]
    owner = context.on_behalf_of or context.actor
    return [f"user:{owner}", "org"]


def _owner_default(context: InvocationContext) -> str:
    owner = context.on_behalf_of or context.actor
    return f"user:{owner}"


class MemoryAdapter:
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
        return [
            VerbSpec(verb_id="memory.remember", noun_id="memory", input_schema={
                "type": "object",
                "properties": {"content": {"type": "string"}, "owner_scope": {"type": "string"},
                               "kind": {"type": "string"}, "source_kind": {"type": "string"},
                               "source_ref": {"type": "string"}, "data_class": {"type": "string"},
                               "relates_to": {"type": "array", "items": {"type": "string"}}},
                "required": ["content"]}, output_schema=_OBJ, consequence="low",
                description="Commit a fact to memory (scoped, provenance-tagged)"),
            VerbSpec(verb_id="memory.recall", noun_id="memory", input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}, "mode": {"type": "string"},
                               "limit": {"type": "integer"}},
                "required": ["query"]}, output_schema=_OBJ, consequence="low",
                description="Recall facts from the caller's permitted scopes, with provenance"),
            VerbSpec(verb_id="memory.improve", noun_id="memory", input_schema={
                "type": "object",
                "properties": {"signal": {"type": "string"}, "target": {"type": "string"}},
                "required": ["signal", "target"]}, output_schema=_OBJ, consequence="low",
                description="Reweight memory from a usage/feedback signal"),
            # Erasure is a compliance right (right-to-be-forgotten), so it is low
            # consequence (not HITL-gated) but always ledgered + audited (SEC-44).
            VerbSpec(verb_id="memory.forget", noun_id="memory", input_schema={
                "type": "object",
                "properties": {"target": {"type": "string"}, "source_ref": {"type": "string"}}},
                output_schema=_OBJ, consequence="low",
                description="Erase a fact/source and its derived edges (complete, ledgered)"),
        ]

    async def execute(
        self, verb: str, params: dict, credential: Credential | None, context: InvocationContext
    ) -> Result:
        scopes = permitted_scopes(context)
        if verb == "memory.remember":
            return await self._remember(params, context, scopes)
        if verb == "memory.recall":
            return await self._recall(params, context, scopes)
        if verb == "memory.improve":
            return await self._improve(params, context)
        if verb == "memory.forget":
            return await self._forget(params, context, scopes)
        return Result.failure(AdapterError(ErrorClass.INVALID, f"unknown verb {verb}"))

    async def health(self) -> str:
        return await self._engine.health()

    # --- audit helper (memory-governance events, contents never logged) ---
    async def _write_audit(self, context, verb, detail, status="ok") -> None:
        if self._audit is None:
            return
        await self._audit.write(AuditEvent(
            tenant_id=context.tenant_id, ts=utcnow(), actor=context.actor,
            actor_tier=context.actor_tier, action_type=ActionType.TOOL_CALL,
            verb=verb, status=status, on_behalf_of=context.on_behalf_of,
            run_id=context.run_id, workspace_id=context.workspace_id, detail=detail,
        ))

    async def _fact_in_scope(self, tenant_id, fact_id, scopes) -> bool:
        f = await self._store.get_memory_fact(tenant_id, fact_id)
        return f is not None and f.owner_scope in set(scopes)

    # --- memory.remember (ingestion boundary: scope + screen + residency) ---
    async def _remember(self, params, context, scopes) -> Result:
        tenant = context.tenant_id
        content = params.get("content", "")
        owner_scope = params.get("owner_scope") or _owner_default(context)
        # SEC-40 at ingestion: a caller may only write into a scope they hold.
        if owner_scope not in set(scopes):
            await self._write_audit(context, "memory.ingest.denied",
                                    {"owner_scope": owner_scope}, status="denied")
            raise GrantMissing(f"cannot write memory to scope {owner_scope}")
        # SEC-42: screen before it becomes memory.
        reason = screen_content(content)
        if reason:
            await self._write_audit(context, "memory.ingest.rejected",
                                    {"reason": reason, "owner_scope": owner_scope}, status="denied")
            return Result.failure(AdapterError(ErrorClass.INVALID, f"content rejected: {reason}"))
        # SEC-05 at ingestion: an API secret / credential must NEVER be persisted
        # into ANY memory engine (Cognee or native) - this is the single boundary
        # every remember passes through before engine.remember, so the guarantee is
        # engine-agnostic. Fail-closed: reject rather than silently store a leak.
        secret_kind = contains_secret(content)
        if secret_kind:
            await self._write_audit(context, "memory.ingest.secret_blocked",
                                    {"secret_kind": secret_kind, "owner_scope": owner_scope},
                                    status="denied")
            return Result.failure(AdapterError(
                ErrorClass.INVALID,
                f"content contains a secret ({secret_kind}); memory ingestion blocked",
            ))
        data_class = params.get("data_class", "standard")
        # SEC-43: sensitive memory must use a local endpoint, else block + audit.
        if data_class == "sensitive" and self._sensitive_endpoint not in self._local_endpoints:
            await self._write_audit(context, "memory.residency.blocked",
                                    {"endpoint": self._sensitive_endpoint}, status="denied")
            raise SensitiveDataMisrouted(
                f"sensitive memory cannot use non-local endpoint {self._sensitive_endpoint}")
        # cross-scope edges: when forbidden, drop edges leaving the permitted scopes.
        relates = [str(r) for r in (params.get("relates_to") or [])]
        if self._cross_scope_edges == "forbidden":
            kept = []
            for r in relates:
                if await self._fact_in_scope(tenant, r, scopes):
                    kept.append(r)
            relates = kept
        fid = uuid.uuid4().hex
        ef = EngineFact(
            id=fid, owner_scope=owner_scope, kind=params.get("kind", "entity"), content=content,
            data_class=data_class, source_kind=params.get("source_kind", "verb_result"),
            source_ref=params.get("source_ref"), relates_to=relates,
        )
        try:
            await self._store.add_memory_fact(MemoryFact(
                id=fid, tenant_id=tenant, owner_scope=owner_scope, engine_ref=fid, kind=ef.kind,
                source_kind=ef.source_kind, source_ref=ef.source_ref, data_class=data_class,
                content=content[:200],
            ))
        except Exception as exc:
            return Result.failure(AdapterError(
                ErrorClass.INTERNAL,
                f"memory ledger write failed: {type(exc).__name__}",
            ))
        try:
            await self._engine.remember(tenant, [ef])
        except Exception as exc:
            await self._store.delete_memory_fact(tenant, fid)
            return Result.failure(AdapterError(
                ErrorClass.UNAVAILABLE,
                f"memory engine write failed: {type(exc).__name__}",
                retryable=True,
            ))
        projections = []
        if self._projections is not None:
            projections = await self._projections.remember(tenant, ef, context)
        return Result.success({
            "fact_ids": [fid],
            "owner_scope": owner_scope,
            "projections": projections,
        })

    # --- memory.recall (retrieval boundary: scope-filter + least-priv audit) ---
    async def _recall(self, params, context, scopes) -> Result:
        tenant = context.tenant_id
        query = params.get("query", "")
        mode = params.get("mode", "graph_completion")
        limit = min(int(params.get("limit", self._max_results)), self._max_results)
        source = "engine"
        projection_refs: dict[str, str | None] = {}
        projected = None
        if self._projections is not None:
            projected = await self._projections.recall(
                tenant, query, scopes=scopes, mode=mode, limit=limit,
                max_hops=self._max_hops, context=context)
        if projected is not None:
            hits = projected.hits
            source = projected.projection_id
            projection_refs = projected.projection_refs
        else:
            hits = await self._engine.recall(
                tenant, query, scopes=scopes, mode=mode, limit=limit, max_hops=self._max_hops)
        # SEC-40 defence-in-depth: re-filter to permitted scopes even if the engine
        # returned anything broader.
        allowed = set(scopes)
        facts = [
            {
                "id": h.fact.id, "owner_scope": h.fact.owner_scope, "kind": h.fact.kind,
                "content": h.fact.content, "data_class": h.fact.data_class,
                "provenance": {"source_kind": h.fact.source_kind, "source_ref": h.fact.source_ref,
                               "hops": h.hops, "path": h.path},
                "projection": {"source": source, "ref": projection_refs.get(h.fact.id),
                               "authority": "kernel_ledger"},
            }
            for h in hits if h.fact.owner_scope in allowed
        ]
        # SEC-45: audit the query/scope/count, never the contents.
        await self._write_audit(context, "memory.recall",
                                {"query": query, "mode": mode, "scopes": scopes, "count": len(facts)})
        return Result.success({"facts": facts, "count": len(facts), "projection_source": source})

    # --- memory.improve (reweight; cannot change scope or grant authority) ---
    async def _improve(self, params, context) -> Result:
        adjusted = await self._engine.improve(
            context.tenant_id, params.get("signal", ""), params.get("target", ""))
        return Result.success({"adjusted": adjusted})

    # --- memory.forget (complete, ledgered, audited erasure) ---
    async def _forget(self, params, context, scopes) -> Result:
        tenant = context.tenant_id
        target = params.get("target")
        source_ref = params.get("source_ref")
        removed = await self._engine.forget(
            tenant, fact_ids=[target] if target else None, source_ref=source_ref, scopes=scopes)
        for fid in removed:
            await self._store.delete_memory_fact(tenant, fid)
        erasure = MemoryErasure(
            id=uuid.uuid4().hex, tenant_id=tenant, requested_by=context.actor,
            target=str(target or source_ref or ""), scope=",".join(scopes),
            engine_confirmed=True, transcript_handled=bool(source_ref),
            facts_removed=len(removed), completed_at=utcnow(),
        )
        await self._store.add_memory_erasure(erasure)
        await self._write_audit(context, "memory.forget",
                                {"target": erasure.target, "facts_removed": len(removed),
                                 "engine_confirmed": True})
        projections = []
        if self._projections is not None and removed:
            projections = await self._projections.forget(tenant, removed, context)
        return Result.success({
            "erasure_id": erasure.id, "removed": removed, "facts_removed": len(removed),
            "engine_confirmed": True, "transcript_handled": erasure.transcript_handled,
            "projections": projections,
        })


def build_memory_adapter(
    engine, store, *, audit=None, config: dict | None = None, projections=None
) -> MemoryAdapter:
    """Construct a MemoryAdapter from a manifest ``memory`` config block."""
    cfg = config or {}
    sensitive = cfg.get("embedding_endpoint", "local-sensitive")
    local = set(cfg.get("local_endpoints") or [sensitive, cfg.get("extraction_endpoint", sensitive)])
    retrieval = cfg.get("retrieval", {}) or {}
    return MemoryAdapter(
        engine, store, audit=audit, sensitive_endpoint=sensitive, local_endpoints=local,
        cross_scope_edges=cfg.get("cross_scope_edges", "forbidden"),
        max_hops=int(retrieval.get("max_hops", 4)),
        max_results=int(retrieval.get("max_results", 20)),
        projections=projections,
    )
