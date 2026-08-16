"""Shared write-gate outcomes for the semantic plane (decision 0029).

``accept_semantic`` closes the previous active version and opens the new one
(SUPERSEDE_EXISTING / ACCEPT_NEW, with the event pair); ``park_candidate``
records a candidate awaiting review. Row builders extracted from
``write_gate.py`` so the decision sequence and the persistence shape read
separately.
"""

from __future__ import annotations

import uuid

from boltrig.models import MemoryFact, utcnow

from .typology import (
    ACCEPT_NEW,
    REQUEST_HUMAN_REVIEW,
    SEMANTIC,
    SUPERSEDE_EXISTING,
)
from .write_gate import GateOutcome, _event


async def accept_semantic(
    store, record, tenant, key, statement, owner_scope, source_kind, source_ref,
    confidence, valid_from, payload, current,
) -> GateOutcome:
    now = utcnow()
    if current is not None:
        current.status = "superseded"
        current.valid_to = now
        await store.update_memory_fact(current)
    fact = MemoryFact(
        id=uuid.uuid4().hex,
        tenant_id=tenant,
        owner_scope=owner_scope,
        engine_ref="",
        kind=SEMANTIC,
        source_kind=source_kind,
        source_ref=source_ref,
        content=statement[:200],
        status="active",
        memory_key=key,
        version=(current.version + 1) if current else 1,
        confidence=confidence,
        valid_from=valid_from or now,
        payload=payload,
        supersedes_id=current.id if current else None,
    )
    await store.add_memory_fact(fact)
    events = [
        _event(
            tenant,
            "memory_activated",
            decision=SUPERSEDE_EXISTING if current else ACCEPT_NEW,
            memory_id=fact.id,
            memory_key=key,
            detail={"version": fact.version, "confidence": confidence},
        )
    ]
    if current is not None:
        events.append(
            _event(
                tenant,
                "memory_superseded",
                memory_id=current.id,
                memory_key=key,
                detail={"by": fact.id, "version": fact.version},
            )
        )
    for evt in events:
        await record(evt)
    return GateOutcome(
        SUPERSEDE_EXISTING if current else ACCEPT_NEW, fact=fact, superseded=current or None
    )


async def park_candidate(
    store, record, tenant, key, statement, owner_scope, source_kind, source_ref,
    confidence, valid_from, payload, reasons,
) -> GateOutcome:
    fact = MemoryFact(
        id=uuid.uuid4().hex,
        tenant_id=tenant,
        owner_scope=owner_scope,
        engine_ref="",
        kind=SEMANTIC,
        source_kind=source_kind,
        source_ref=source_ref,
        content=statement[:200],
        status="candidate",
        memory_key=key,
        confidence=confidence,
        valid_from=valid_from,
        payload=payload,
    )
    await store.add_memory_fact(fact)
    await record(
        _event(
            tenant,
            "candidate_created",
            decision=REQUEST_HUMAN_REVIEW,
            memory_id=fact.id,
            memory_key=key,
            detail={"confidence": confidence, "reasons": reasons},
        )
    )
    return GateOutcome(REQUEST_HUMAN_REVIEW, reasons, fact=fact)


__all__ = ["accept_semantic", "park_candidate"]
