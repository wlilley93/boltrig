"""The candidate-review plane of the typed write gate (decision 0029).

Explicit review is the ONLY activation path for candidates (MEM-TYP-06).
Extracted from ``write_gate.py`` so the review policy - close the previous
active version, activate the candidate under the reviewer's name, record the
approved/activated/superseded event triple - reads as one unit.
"""

from __future__ import annotations

from boltrig.models import utcnow

from .typology import ACCEPT_NEW, REJECT_UNSUPPORTED
from .write_gate import GateOutcome, _event


async def review_candidate(
    store, lock, record, tenant: str, candidate_id: str, *, approve: bool, reviewer: str
) -> GateOutcome:
    candidate = await store.get_memory_fact(tenant, candidate_id)
    if candidate is None or candidate.status != "candidate":
        return GateOutcome(
            REJECT_UNSUPPORTED, [f"no candidate {candidate_id!r} awaiting review"]
        )
    if not approve:
        candidate.status = "rejected"
        await store.update_memory_fact(candidate)
        await record(
            _event(
                tenant,
                "candidate_rejected",
                decision="REVIEW_REJECTED",
                memory_id=candidate.id,
                memory_key=candidate.memory_key,
                detail={"reviewer": reviewer},
            )
        )
        return GateOutcome("REVIEW_REJECTED", fact=candidate)

    key = candidate.memory_key
    async with lock(tenant, str(key or candidate.id)):
        previous = (
            await store.get_active_memory_fact(tenant, key) if key else None
        )
        if previous is not None:
            previous.status = "superseded"
            previous.valid_to = utcnow()
            await store.update_memory_fact(previous)
        candidate.status = "active"
        candidate.version = (previous.version + 1) if previous else 1
        candidate.supersedes_id = previous.id if previous else None
        candidate.valid_from = candidate.valid_from or utcnow()
        candidate.payload = {**candidate.payload, "approved_by": reviewer}
        await store.update_memory_fact(candidate)
        events = [
            _event(
                tenant,
                "memory_approved",
                memory_id=candidate.id,
                memory_key=key,
                detail={"reviewer": reviewer},
            ),
            _event(
                tenant,
                "memory_activated",
                decision=ACCEPT_NEW,
                memory_id=candidate.id,
                memory_key=key,
                detail={"version": candidate.version},
            ),
        ]
        if previous is not None:
            events.append(
                _event(
                    tenant,
                    "memory_superseded",
                    memory_id=previous.id,
                    memory_key=key,
                    detail={"by": candidate.id, "version": candidate.version},
                )
            )
        for evt in events:
            await record(evt)
    return GateOutcome("REVIEW_APPROVED", fact=candidate, superseded=previous)


__all__ = ["review_candidate"]
