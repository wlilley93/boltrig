"""The typed-memory write gate (decision 0029): the LLM proposes, this decides.

Nothing becomes durable semantic/procedural memory except through this gate.
It enforces, deterministically and offline-testably:

  * closed predicate registries - a fact must occupy a known slot
    (REJECT_INVALID_PREDICATE, MEM-TYP-01);
  * durability - present-state wording is working state or episode material,
    never a durable fact (REJECT_TRANSIENT, MEM-TYP-02);
  * source precedence - a lower-authority source never silently overwrites a
    higher-authority current value (REJECT_LOWER_AUTHORITY, MEM-TYP-01);
  * supersession - a value change closes the previous ledger version and opens
    a new one; exactly one row per slot stays active (the DB partial unique
    index arbitrates any race the per-slot lock misses);
  * procedure governance - procedural proposals are ALWAYS born candidates;
    only an explicit review activates a version (MEM-TYP-03/MEM-TYP-06);
  * episode terminality - only completed, evidenced experience is written
    (REJECT_NOT_TERMINAL).

Every decision appends a machine-readable ``memory_events`` row (policy
version, decision code, validator results) so the write policy can be tuned
from evidence. The gate is store-only: engine writes and projection fanout are
orchestrated by the adapter, ledger-first, with compensation on engine failure
(matching the Round Five ``_remember`` discipline).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from boltrig.models import MemoryEvent, MemoryFact

from .typology import (
    CONFIDENCE_ACCEPT,
    CONFIDENCE_REVIEW,
    DEFAULT_AUTHORITY,
    CONFIRM_EXISTING,
    REJECT_INVALID_PREDICATE,
    REJECT_LOWER_AUTHORITY,
    REJECT_UNSUPPORTED,
    REJECT_TRANSIENT,
    authority_rank,
    looks_transient,
    predicate_allowed,
    semantic_memory_key,
)

POLICY_VERSION = "typed-write-v1"


@dataclass
class GateOutcome:
    """One gate decision plus the rows it produced, for the adapter to project.

    ``superseded``/``confirmed`` let the caller compensate a failed engine
    write by restoring the ledger to its pre-decision state.
    """

    decision: str
    reasons: list[str] = field(default_factory=list)
    fact: MemoryFact | None = None  # the new active/candidate row
    superseded: MemoryFact | None = None  # the closed previous active row
    confirmed: MemoryFact | None = None  # the existing row a CONFIRM touched


def _event(
    tenant: str,
    kind: str,
    *,
    decision: str | None = None,
    memory_id: str | None = None,
    memory_key: str | None = None,
    detail: dict | None = None,
) -> MemoryEvent:
    return MemoryEvent(
        id=uuid.uuid4().hex,
        tenant_id=tenant,
        event=kind,
        memory_id=memory_id,
        memory_key=memory_key,
        decision=decision,
        policy_version=POLICY_VERSION,
        detail=detail or {},
    )


def _norm(value) -> str:
    return str(value or "").strip().lower()


def _current_value_verdict(source_authority: str | None, current) -> tuple[str, int, int]:
    """How an incoming value relates to the slot's current value: reject_lower
    (lower authority loses), conflict (equal authority, different value -
    review), or proceed (strictly higher authority may supersede). The ranks
    ride along for the rejection detail."""

    incoming = authority_rank(source_authority)
    holding = authority_rank(current.payload.get("source_authority"))
    if incoming < holding:
        return "reject_lower", incoming, holding
    if incoming == holding:
        return "conflict", incoming, holding
    return "proceed", incoming, holding


def _semantic_preflight(
    subject_type: str,
    predicate: str,
    statement: str,
    is_durable: bool | None,
    confidence: float,
) -> tuple[str, list[str]] | None:
    """The lock-free first-pass screens; None means the proposal may proceed."""

    if not predicate_allowed(subject_type, predicate):
        return REJECT_INVALID_PREDICATE, [
            f"predicate {predicate!r} is not in the {subject_type!r} registry"
        ]
    if is_durable is False or (is_durable is None and looks_transient(statement)):
        marker = looks_transient(statement)
        return REJECT_TRANSIENT, [
            "statement describes present state, not a durable attribute"
            + (f" (marker {marker!r})" if marker else "")
        ]
    if confidence < CONFIDENCE_REVIEW:
        return REJECT_UNSUPPORTED, [f"confidence {confidence:.2f} below review floor"]
    return None


class TypedWriteGate:
    """Store-only decision maker for typed memory candidates."""

    def __init__(self, store) -> None:
        self._store = store
        # Per-slot serialisation (spec: writes to one slot must not interleave).
        # The DB partial unique index remains the authoritative arbiter; the
        # lock keeps the read-decide-write sequence from racing in-process.
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    def _lock(self, tenant: str, memory_key: str) -> asyncio.Lock:
        return self._locks.setdefault((tenant, memory_key), asyncio.Lock())

    async def _record(self, event: MemoryEvent) -> None:
        await self._store.add_memory_event(event)

    # --- semantic -----------------------------------------------------------
    async def propose_semantic(
        self,
        tenant: str,
        *,
        subject_type: str,
        subject_id: str,
        predicate: str,
        value,
        statement: str,
        owner_scope: str,
        confidence: float = 0.0,
        source_authority: str | None = None,
        source_kind: str = "verb_result",
        source_ref: str | None = None,
        is_durable: bool | None = None,
        valid_from: datetime | None = None,
    ) -> GateOutcome:
        preflight = _semantic_preflight(
            subject_type, predicate, statement, is_durable, confidence
        )
        if preflight is not None:
            decision, reasons = preflight
            detail = {"predicate": predicate} if decision == REJECT_INVALID_PREDICATE else None
            return await self._rejected(
                tenant, decision, reasons, detail=detail
            )

        key = semantic_memory_key(subject_type, subject_id, predicate, owner_scope)
        async with self._lock(tenant, key):
            current = await self._store.get_active_memory_fact(tenant, key)
            payload = {
                "subject_type": subject_type,
                "subject_id": subject_id,
                "predicate": predicate,
                "value": value,
                "source_authority": source_authority or DEFAULT_AUTHORITY,
            }
            confirmed = await self._maybe_confirm(
                tenant, key, current, value, confidence
            )
            if confirmed is not None:
                return confirmed
            if current is not None:
                verdict, incoming, holding = _current_value_verdict(source_authority, current)
                if verdict == "reject_lower":
                    return await self._rejected(
                        tenant,
                        REJECT_LOWER_AUTHORITY,
                        [
                            f"source authority {source_authority!r} ({incoming}) cannot "
                            f"overwrite current authority "
                            f"{current.payload.get('source_authority')!r} ({holding})"
                        ],
                        memory_key=key,
                        detail={"incoming_rank": incoming, "holding_rank": holding},
                    )
                if verdict == "conflict":
                    return await self._candidate(
                        tenant, key, statement, owner_scope, source_kind, source_ref,
                        confidence, valid_from, payload,
                        ["equal-authority conflict with the current value; needs review"],
                    )

            # No current value, or strictly higher incoming authority.
            auto_accept = authority_rank(source_authority) >= 3 or (
                authority_rank(source_authority) >= 2 and confidence >= CONFIDENCE_ACCEPT
            )
            if current is None and not auto_accept:
                return await self._candidate(
                    tenant, key, statement, owner_scope, source_kind, source_ref,
                    confidence, valid_from, payload,
                    ["new slot from weak authority; needs review"],
                )
            return await self._accept(
                tenant, key, statement, owner_scope, source_kind, source_ref,
                confidence, valid_from, payload, current,
            )

    # --- episodic -----------------------------------------------------------
    async def propose_episodic(
        self,
        tenant: str,
        *,
        title: str,
        retrieval_text: str,
        outcome: str,
        is_terminal: bool,
        owner_scope: str,
        situation: str = "",
        attempted: list[str] | None = None,
        failed_attempts: list[str] | None = None,
        root_cause: str | None = None,
        resolution: str | None = None,
        task_family: str = "general",
        tools_used: list[str] | None = None,
        environment: dict | None = None,
        outcome_evidence: list[str] | None = None,
        confidence: float = 0.0,
        source_kind: str = "verb_result",
        source_ref: str | None = None,
    ) -> GateOutcome:
        from .write_gate_planes import propose_episode

        return await propose_episode(
            self._store,
            self._record,
            self._rejected,
            tenant,
            title=title,
            retrieval_text=retrieval_text,
            outcome=outcome,
            is_terminal=is_terminal,
            owner_scope=owner_scope,
            situation=situation,
            attempted=attempted or [],
            failed_attempts=failed_attempts or [],
            root_cause=root_cause,
            resolution=resolution,
            task_family=task_family,
            tools_used=tools_used or [],
            environment=environment or {},
            outcome_evidence=outcome_evidence or [],
            confidence=confidence,
            source_kind=source_kind,
            source_ref=source_ref,
        )

    # --- procedural ---------------------------------------------------------
    async def propose_procedural(
        self,
        tenant: str,
        *,
        procedure_key: str,
        title: str,
        body_markdown: str,
        owner_scope: str,
        summary: str = "",
        applies_to_roles: list[str] | None = None,
        applies_to_workflows: list[str] | None = None,
        invariants: list[str] | None = None,
        prohibited_actions: list[str] | None = None,
        confidence: float = 0.0,
        source_kind: str = "feedback",
        source_ref: str | None = None,
    ) -> GateOutcome:
        from .write_gate_planes import propose_procedure

        return await propose_procedure(
            self._store,
            self._record,
            self._rejected,
            tenant,
            procedure_key=procedure_key,
            title=title,
            body_markdown=body_markdown,
            owner_scope=owner_scope,
            summary=summary,
            applies_to_roles=applies_to_roles or [],
            applies_to_workflows=applies_to_workflows or [],
            invariants=invariants or [],
            prohibited_actions=prohibited_actions or [],
            confidence=confidence,
            source_kind=source_kind,
            source_ref=source_ref,
        )

    # --- candidate review (the ONLY activation path for candidates) ---------
    async def review_candidate(
        self, tenant: str, candidate_id: str, *, approve: bool, reviewer: str
    ) -> GateOutcome:
        from .write_gate_review import review_candidate

        return await review_candidate(
            self._store, self._lock, self._record, tenant, candidate_id,
            approve=approve, reviewer=reviewer,
        )

    async def _maybe_confirm(self, tenant, key, current, value, confidence):
        """CONFIRM_EXISTING when the normalised incoming value equals the active
        value - a re-observation, not a new fact."""

        if current is None or _norm(current.payload.get("value")) != _norm(value):
            return None
        await self._record(
            _event(
                tenant,
                "memory_confirmed",
                decision=CONFIRM_EXISTING,
                memory_id=current.id,
                memory_key=key,
                detail={"confidence": confidence},
            )
        )
        return GateOutcome(
            CONFIRM_EXISTING, ["value unchanged; current fact confirmed"], confirmed=current
        )

    # --- shared outcomes ------------------------------------------------------
    async def _accept(
        self, tenant, key, statement, owner_scope, source_kind, source_ref,
        confidence, valid_from, payload, current,
    ) -> GateOutcome:
        from .write_gate_outcomes import accept_semantic

        return await accept_semantic(
            self._store, self._record, tenant, key, statement, owner_scope,
            source_kind, source_ref, confidence, valid_from, payload, current,
        )

    async def _candidate(
        self, tenant, key, statement, owner_scope, source_kind, source_ref,
        confidence, valid_from, payload, reasons,
    ) -> GateOutcome:
        from .write_gate_outcomes import park_candidate

        return await park_candidate(
            self._store, self._record, tenant, key, statement, owner_scope,
            source_kind, source_ref, confidence, valid_from, payload, reasons,
        )

    async def _rejected(
        self, tenant, decision, reasons, *, memory_key=None, detail=None
    ) -> GateOutcome:
        await self._record(
            _event(
                tenant,
                "candidate_rejected",
                decision=decision,
                memory_key=memory_key,
                detail={**(detail or {}), "reasons": reasons},
            )
        )
        return GateOutcome(decision, reasons)


__all__ = ["GateOutcome", "POLICY_VERSION", "TypedWriteGate"]
