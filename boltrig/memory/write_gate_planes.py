"""Episodic and procedural write-gate planes (decision 0029).

The append-only episode writer and the always-candidate procedure writer,
extracted from ``write_gate.py`` so each policy stays independently readable.
Both take the gate's collaborators (``store``, ``record``, ``reject``) rather
than the gate itself: the policy is the function, the plumbing is shared.
"""

from __future__ import annotations

import uuid

from boltrig.models import MemoryEvent, MemoryFact

from .typology import (
    CONFIDENCE_REVIEW,
    EPISODE_OUTCOMES,
    PROCEDURAL,
    ACCEPT_NEW,
    REJECT_INVALID_PREDICATE,
    REJECT_NOT_TERMINAL,
    REJECT_UNSUPPORTED,
    REQUEST_HUMAN_REVIEW,
    procedure_memory_key,
    valid_procedure_key,
)
from .write_gate import GateOutcome, _event


def episodic_preflight(
    retrieval_text: str, outcome: str, is_terminal: bool, confidence: float
) -> tuple[str, list[str]] | None:
    """Lock-free episode screens; None means the episode may be written."""

    if not is_terminal:
        return REJECT_NOT_TERMINAL, ["run has not reached a terminal/reviewable state"]
    if not retrieval_text.strip():
        return REJECT_UNSUPPORTED, ["retrieval_text (the incoming problem) is required"]
    if outcome not in EPISODE_OUTCOMES:
        return REJECT_UNSUPPORTED, [
            f"outcome {outcome!r} is not one of {sorted(EPISODE_OUTCOMES)}"
        ]
    if confidence < CONFIDENCE_REVIEW:
        return REJECT_UNSUPPORTED, [f"confidence {confidence:.2f} below review floor"]
    return None


async def propose_episode(store, record, reject, tenant: str, **kw) -> GateOutcome:
    preflight = episodic_preflight(
        kw["retrieval_text"], kw["outcome"], kw["is_terminal"], kw["confidence"]
    )
    if preflight is not None:
        decision, reasons = preflight
        return await reject(tenant, decision, reasons)

    # Append-only experience: `memory_key` unset, no supersession path.
    fact = MemoryFact(
        id=uuid.uuid4().hex,
        tenant_id=tenant,
        owner_scope=kw["owner_scope"],
        engine_ref="",
        kind="episodic",
        source_kind=kw["source_kind"],
        source_ref=kw["source_ref"],
        content=kw["title"][:200],
        status="active",
        confidence=kw["confidence"],
        payload={
            "title": kw["title"],
            "retrieval_text": kw["retrieval_text"],
            "situation": kw["situation"],
            "attempted": kw["attempted"],
            "failed_attempts": kw["failed_attempts"],
            "root_cause": kw["root_cause"],
            "resolution": kw["resolution"],
            "outcome": kw["outcome"],
            "task_family": kw["task_family"],
            "tools_used": kw["tools_used"],
            "environment": kw["environment"],
            "outcome_evidence": kw["outcome_evidence"],
        },
    )
    await store.add_memory_fact(fact)
    await record(
        _event(
            tenant,
            "memory_activated",
            decision=ACCEPT_NEW,
            memory_id=fact.id,
            detail={"task_family": kw["task_family"], "outcome": kw["outcome"]},
        )
    )
    return GateOutcome(ACCEPT_NEW, fact=fact)


async def propose_procedure(store, record, reject, tenant: str, **kw) -> GateOutcome:
    procedure_key = kw["procedure_key"]
    if not valid_procedure_key(procedure_key):
        return await reject(
            tenant,
            REJECT_INVALID_PREDICATE,
            [
                "procedure_key must be ::-separated with non-empty parts, e.g. "
                "platform::coding-agent::security-diff-review"
            ],
            detail={"procedure_key": procedure_key},
        )
    # No amount of confidence activates a procedure: always a candidate.
    key = procedure_memory_key(procedure_key, kw["owner_scope"])
    fact = MemoryFact(
        id=uuid.uuid4().hex,
        tenant_id=tenant,
        owner_scope=kw["owner_scope"],
        engine_ref="",
        kind=PROCEDURAL,
        source_kind=kw["source_kind"],
        source_ref=kw["source_ref"],
        content=kw["title"][:200],
        status="candidate",
        confidence=kw["confidence"],
        payload={
            "procedure_key": procedure_key,
            "title": kw["title"],
            "summary": kw["summary"],
            "body_markdown": kw["body_markdown"],
            "applies_to_roles": kw["applies_to_roles"] or ["*"],
            "applies_to_workflows": kw["applies_to_workflows"] or ["*"],
            "invariants": kw["invariants"],
            "prohibited_actions": kw["prohibited_actions"],
        },
    )
    await store.add_memory_fact(fact)
    await record(
        _event(
            tenant,
            "candidate_created",
            decision=REQUEST_HUMAN_REVIEW,
            memory_id=fact.id,
            memory_key=key,
            detail={"procedure_key": procedure_key},
        )
    )
    return GateOutcome(REQUEST_HUMAN_REVIEW, ["procedure proposal awaits review"], fact=fact)


__all__ = [
    "MemoryEvent",
    "episodic_preflight",
    "propose_episode",
    "propose_procedure",
]
