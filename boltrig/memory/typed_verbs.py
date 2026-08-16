"""Typed-plane verb handlers for the governed memory adapter (decision 0029).

Extends the MemoryWriteMixin discipline to the typed planes: the LLM (or a
human) PROPOSES through ``memory.propose``; the deterministic gate decides;
only accepted rows reach the engine and projections, ledger-first with
compensation on engine failure. ``memory.bundle`` is the read side: typed
recall assembled into an authority-ordered prompt bundle. ``memory.resolve``
is the deterministic current-value lookup. ``memory.candidates.review`` is the
only activation path for candidates.
"""

from __future__ import annotations

from boltrig.adapters.base import AdapterError, ErrorClass, Result
from boltrig.models import GrantMissing, InvocationContext

from .adapter_writes import owner_default
from .bundle import build_memory_bundle, render_prompt
from .bundle_config import config_from_overrides
from .engine import EngineFact
from .proposers import proposer_for
from .typology import (
    ACCEPTED_DECISIONS,
    CONFIRM_EXISTING,
    PROCEDURAL,
    SEMANTIC,
    WRITABLE_PLANES,
)
from .write_gate import TypedWriteGate

_ENGINE_TEXT_LIMIT = 20_000


def _plane_text(plane: str, params: dict) -> str:
    if plane == "episodic":
        return str(params.get("retrieval_text") or "")
    if plane == PROCEDURAL:
        title = str(params.get("title") or "")
        summary = str(params.get("summary") or "")
        return f"{title}\n\n{summary}".strip()
    return str(params.get("statement") or "")


class TypedVerbMixin:
    """Handlers mixed into MemoryAdapter (shares _store/_engine/_projections)."""

    def _gate(self) -> TypedWriteGate:
        gate = getattr(self, "_typed_gate", None)
        if gate is None:
            gate = TypedWriteGate(self._store)
            self._typed_gate = gate
        return gate

    def _gate_for(self, plane: str):
        return proposer_for(self._gate(), plane)

    # --- memory.propose ------------------------------------------------------
    async def _propose(self, params, context: InvocationContext, scopes) -> Result:
        tenant = context.tenant_id
        plane = str(params.get("plane") or "")
        if plane not in WRITABLE_PLANES:
            return Result.failure(
                AdapterError(
                    ErrorClass.INVALID,
                    f"plane must be one of {sorted(WRITABLE_PLANES)}; source and working "
                    "state are not writable memory",
                )
            )
        owner_scope = str(params.get("owner_scope") or self._owner_default(context))
        if owner_scope not in set(scopes):
            raise GrantMissing(f"cannot write memory to scope {owner_scope}")
        text = _plane_text(plane, params)
        refused = await self._refuse_unsafe_content(text, owner_scope, context, scopes)
        if refused is not None:
            return refused
        outcome = await self._gate_for(plane).run(tenant, owner_scope, text, params)

        if outcome.decision not in ACCEPTED_DECISIONS or outcome.fact is None:
            await self._write_audit(
                context,
                "memory.propose",
                {
                    "plane": plane,
                    "decision": outcome.decision,
                    "candidate_id": outcome.fact.id if outcome.fact else None,
                },
                status="rejected" if outcome.fact is None else "review_required",
            )
            return Result.success(
                {
                    "decision": outcome.decision,
                    "reasons": outcome.reasons,
                    "candidate_id": outcome.fact.id if outcome.fact else None,
                    "persisted": outcome.fact is not None,
                }
            )
        if outcome.decision == CONFIRM_EXISTING:
            await self._write_audit(
                context, "memory.propose", {"plane": plane, "decision": CONFIRM_EXISTING}
            )
            return Result.success(
                {"decision": CONFIRM_EXISTING, "reasons": outcome.reasons, "persisted": False}
            )
        return await self._commit_accepted(plane, outcome, text, owner_scope, tenant, context)

    async def _commit_accepted(self, plane, outcome, text, owner_scope, tenant, context):
        """Accepted: engine + projections, ledger-first with compensation."""

        fact = outcome.fact
        engine_fact = EngineFact(
            id=fact.id,
            owner_scope=owner_scope,
            kind=fact.kind,
            content=text[:_ENGINE_TEXT_LIMIT],
            data_class="standard",
            source_kind=fact.source_kind,
            source_ref=fact.source_ref,
        )
        try:
            await self._engine.remember(tenant, [engine_fact])
        except Exception as exc:
            await self._compensate(tenant, outcome)
            return Result.failure(
                AdapterError(
                    ErrorClass.UNAVAILABLE,
                    f"memory engine write failed: {type(exc).__name__}",
                    retryable=True,
                )
            )
        fact.engine_ref = fact.id
        await self._store.update_memory_fact(fact)
        projections = []
        if self._projections is not None:
            projections = await self._projections.remember(tenant, engine_fact, context)
        await self._retire_superseded(tenant, outcome, context)
        await self._write_audit(
            context,
            "memory.propose",
            {"plane": plane, "decision": outcome.decision, "memory_id": fact.id},
        )
        return Result.success(
            {
                "decision": outcome.decision,
                "reasons": outcome.reasons,
                "memory_id": fact.id,
                "version": fact.version,
                "status": fact.status,
                "persisted": True,
                "projections": projections,
            }
        )

    # --- memory.bundle -------------------------------------------------------
    async def _bundle(self, params, context: InvocationContext, scopes) -> Result:
        tenant = context.tenant_id
        query = str(params.get("query") or "")
        limit = self._max_results

        async def recall(text: str, permitted: list[str]):
            return await self._engine.recall(
                tenant, text, scopes=permitted, mode="similarity", limit=limit,
                max_hops=self._max_hops,
            )

        config = config_from_overrides(
            params.get("config"), defaults=getattr(self, "_typed_config", None)
        )
        owner_scope = str(params.get("owner_scope") or self._owner_default(context))
        bundle = await build_memory_bundle(
            self._store,
            recall,
            tenant,
            query=query,
            scopes=scopes,
            owner_scope=owner_scope,
            subjects=params.get("subjects") or [],
            role=str(params.get("agent_role") or ""),
            workflow=str(params.get("workflow") or ""),
            working_context=params.get("working_context"),
            config=config,
        )
        prompt = render_prompt(bundle, budget=config.budget)
        # SEC-45 discipline: the `_write_audit` payload carries counts.
        await self._write_audit(
            context,
            "memory.bundle",
            {
                "config": config.label,
                "semantic": len(bundle["semantic_facts"]),
                "episodic": len(bundle["episodes"]),
                "procedural": len(bundle["procedures"]),
                "source": len(bundle["source_context"]),
            },
        )
        return Result.success(
            {
                "config_label": bundle["config_label"],
                "semantic_facts": [_fact_public(f) for f in bundle["semantic_facts"]],
                "episodes": [
                    {
                        "id": e["id"],
                        "score": e["score"],
                        "title": e["payload"].get("title"),
                        "outcome": e["payload"].get("outcome"),
                        "retrieval_text": e["payload"].get("retrieval_text") or e["content"],
                        "failed_attempts": e["payload"].get("failed_attempts"),
                        "resolution": e["payload"].get("resolution"),
                    }
                    for e in bundle["episodes"]
                ],
                "procedures": [_fact_public(f) for f in bundle["procedures"]],
                "source_context": [
                    {"id": s["id"], "score": s["score"], "content": s["content"]}
                    for s in bundle["source_context"]
                ],
                "working_context": bundle["working_context"],
                "warnings": bundle["warnings"],
                "provenance": bundle["provenance"],
                "char_usage": bundle["char_usage"],
                "prompt": prompt,
            }
        )

    # --- memory.resolve (deterministic current values) ------------------------
    async def _resolve(self, params, context: InvocationContext, scopes) -> Result:
        tenant = context.tenant_id
        subject_type = str(params.get("subject_type") or "")
        subject_id = str(params.get("subject_id") or "")
        if not subject_type or not subject_id:
            return Result.failure(
                AdapterError(ErrorClass.INVALID, "subject_type and subject_id are required")
            )
        facts = await self._store.list_active_subject_facts(
            tenant, scopes, subject_type, subject_id
        )
        predicates = {str(p) for p in params.get("predicates") or []}
        if predicates:
            facts = [f for f in facts if (f.payload or {}).get("predicate") in predicates]
        allowed = set(scopes)
        facts = [f for f in facts if f.owner_scope in allowed]
        await self._write_audit(
            context,
            "memory.resolve",
            {"subject_type": subject_type, "subject_id": subject_id, "count": len(facts)},
        )
        return Result.success(
            {"facts": [_fact_public(f) for f in facts], "count": len(facts)}
        )

    # --- memory.candidates.review (the only activation path) ------------------
    async def _review_candidate(self, params, context: InvocationContext, scopes) -> Result:
        tenant = context.tenant_id
        candidate_id = str(params.get("candidate_id") or "")
        decision = str(params.get("decision") or "")
        if decision not in {"approve", "reject"}:
            return Result.failure(
                AdapterError(ErrorClass.INVALID, "decision must be 'approve' or 'reject'")
            )
        candidate = await self._store.get_memory_fact(tenant, candidate_id)
        if candidate is None or candidate.owner_scope not in set(scopes):
            # Hidden and missing are indistinguishable (SEC-40).
            return Result.failure(AdapterError(ErrorClass.INVALID, "unknown candidate"))
        outcome = await self._gate().review_candidate(
            tenant, candidate_id, approve=decision == "approve", reviewer=context.actor
        )
        if outcome.decision == "REJECT_UNSUPPORTED":
            return Result.failure(
                AdapterError(ErrorClass.INVALID, outcome.reasons[0] if outcome.reasons
                             else "no candidate awaiting review")
            )
        if decision == "approve" and outcome.fact is not None:
            failure = await self._project_reviewed_fact(tenant, outcome, context)
            if failure is not None:
                return failure
        await self._write_audit(
            context,
            "memory.candidates.review",
            {"candidate_id": candidate_id, "approved": decision == "approve"},
        )
        return Result.success(
            {
                "decision": outcome.decision,
                "memory_id": candidate_id,
                "status": outcome.fact.status if outcome.fact else None,
                "version": outcome.fact.version if outcome.fact else None,
                "superseded_id": outcome.superseded.id if outcome.superseded else None,
            }
        )

    # --- shared helpers --------------------------------------------------------
    async def _project_reviewed_fact(self, tenant, outcome, context) -> Result | None:
        """Engine + projection write for a review-activated fact; None on success."""

        fact = outcome.fact
        payload = fact.payload or {}
        text = _plane_text(
            PROCEDURAL,
            {"title": payload.get("title") or fact.content,
             "summary": payload.get("summary") or ""},
        )
        if fact.kind == SEMANTIC:
            text = fact.content or ""
        engine_fact = EngineFact(
            id=fact.id,
            owner_scope=fact.owner_scope,
            kind=fact.kind,
            content=text[:_ENGINE_TEXT_LIMIT],
            source_kind=fact.source_kind,
            source_ref=fact.source_ref,
        )
        try:
            await self._engine.remember(tenant, [engine_fact])
        except Exception as exc:
            return Result.failure(
                AdapterError(
                    ErrorClass.UNAVAILABLE,
                    f"memory engine write failed: {type(exc).__name__}",
                    retryable=True,
                )
            )
        fact.engine_ref = fact.id
        await self._store.update_memory_fact(fact)
        if self._projections is not None:
            await self._projections.remember(tenant, engine_fact, context)
        await self._retire_superseded(tenant, outcome, context)
        return None

    async def _compensate(self, tenant, outcome) -> None:
        """Undo the ledger transition when the engine write fails."""

        if outcome.fact is not None:
            await self._store.delete_memory_fact(tenant, outcome.fact.id)
        if outcome.superseded is not None:
            previous = outcome.superseded
            previous.status = "active"
            previous.valid_to = None
            await self._store.update_memory_fact(previous)

    async def _retire_superseded(self, tenant, outcome, context) -> list:
        """Remove a superseded value's engine node + projections; keep history."""

        previous = outcome.superseded
        if previous is None or not previous.engine_ref:
            return []
        removed = await self._engine.forget(tenant, fact_ids=[previous.engine_ref], scopes=None)
        projections = []
        if self._projections is not None and removed:
            projections = await self._projections.forget(tenant, removed, context)
        return projections

    def _owner_default(self, context: InvocationContext) -> str:
        return owner_default(context)


def _fact_public(fact) -> dict:
    payload = fact.payload or {}
    return {
        "id": fact.id,
        "memory_key": fact.memory_key,
        "owner_scope": fact.owner_scope,
        "kind": fact.kind,
        "status": fact.status,
        "version": fact.version,
        "value": payload.get("value"),
        "statement": fact.content,
        "confidence": fact.confidence,
        "valid_from": fact.valid_from.isoformat() if fact.valid_from else None,
        "valid_to": fact.valid_to.isoformat() if fact.valid_to else None,
        "source_kind": fact.source_kind,
        "source_ref": fact.source_ref,
        "payload": payload,
        "created_at": fact.created_at.isoformat() if fact.created_at else None,
    }


__all__ = ["TypedVerbMixin"]
