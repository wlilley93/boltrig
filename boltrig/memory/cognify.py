"""The cognify pipeline (Epic ING): transcripts/documents -> the memory graph.

Ingestion is a durable-or-local workflow: it classifies, assigns owner-scope at
ingestion (SEC-40), screens content for injection/malware (SEC-42), naively
extracts facts (the reference engine does keyword/edge work; Cognee does real
entity/relationship extraction), and commits them through the memory.remember
verb - so every committed fact passes the kernel chokepoint and carries provenance
back to its source (US-LRN-04). Sensitive sources route extraction/embedding to a
local endpoint via the adapter's residency check (SEC-43). Each run is recorded in
``memory_ingestions``; with a durable executor it survives restarts (US-ING-03),
and offline it runs inline (P9).
"""

from __future__ import annotations

import uuid

from boltrig.models import (
    BoltrigError,
    InvocationContext,
    MemoryIngestion,
    PendingHuman,
    utcnow,
)

from .adapter import screen_content


async def cognify(
    kernel,
    tenant_id: str,
    *,
    source_kind: str,
    source_ref: str,
    owner_scope: str,
    items: list[str],
    context: InvocationContext,
    executor=None,
) -> MemoryIngestion:
    """Cognify ``items`` from one source into scoped, provenance-tagged memory.

    Records a ``memory_ingestions`` row through its lifecycle (screening ->
    cognifying -> done | rejected). Items that fail the injection/malware screen
    are dropped and the run is marked ``rejected`` if nothing survived. Each
    surviving item is committed via ``memory.remember`` (the chokepoint)."""
    ing = MemoryIngestion(
        id=uuid.uuid4().hex, tenant_id=tenant_id, source_kind=source_kind,
        source_ref=source_ref, owner_scope=owner_scope, status="screening",
        hatchet_run_id=(executor.new_run_id() if executor and getattr(executor, "durable", False)
                        else None),
    )
    await kernel.store.add_memory_ingestion(ing)

    clean: list[str] = []
    rejected = 0
    for text in items:
        if screen_content(text):
            rejected += 1
            continue
        clean.append(text)

    ing.screened = True
    if not clean:
        ing.status = "rejected"
        ing.detail = {"rejected_items": rejected}
        await kernel.store.update_memory_ingestion(ing)
        return ing

    ing.status = "cognifying"
    await kernel.store.update_memory_ingestion(ing)

    async def _commit_all() -> int:
        added = 0
        for text in clean:
            try:
                out = await kernel.invoke("memory", "memory.remember", {
                    "content": text, "owner_scope": owner_scope, "kind": "document_chunk",
                    "source_kind": source_kind, "source_ref": source_ref,
                }, context)
                added += len(out.get("fact_ids", []))
            except PendingHuman:
                # A policy pause is control flow, not a bad source item. Hiding
                # it here used to turn an approval-required batch into a false
                # ``done`` result with zero committed facts.
                raise
            except BoltrigError:
                # a single bad item should not fail the whole run (P9)
                continue
        return added

    if executor is not None and getattr(executor, "durable", False):
        added = await executor.run_step("cognify", _commit_all, run_id=ing.hatchet_run_id)
    else:
        added = await _commit_all()

    ing.facts_added = added
    ing.status = "done"
    ing.detail = {"rejected_items": rejected, "engine_durable": bool(
        executor and getattr(executor, "durable", False))}
    ing.completed_at = utcnow()
    await kernel.store.update_memory_ingestion(ing)
    return ing
