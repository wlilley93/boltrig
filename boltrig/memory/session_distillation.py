"""Distil a conversation into memory once it has gone quiet (`ingest.on_session_end`).

The manifest has shipped ``memory.ingest.on_session_end: true`` and the admin
console has offered it as a toggle, while NOTHING read either. It was a switch for
behaviour that did not exist, which is worse than an absent feature: an operator
who turns it on believes conversations are being distilled and they are not.

"When it closes" needed defining, because a chat thread has no close event - the
user simply stops typing. The Principal chose an IDLE WINDOW, ~1 hour, so a thread
untouched for that long is treated as ended.

Two properties this must have, and both are load-bearing:

* **Idempotent.** A sweep runs repeatedly over the same threads. Distilling twice
  writes the same content into 365-day memory twice, so every distillation records
  a ``MemoryIngestion`` keyed ``source_kind='conversation'``/``source_ref=<id>``
  and a thread that already has one is skipped.
* **Deletion-respecting.** ``list_idle_conversations`` filters ``status='active'``.
  retention.py soft-closes a deleted thread to CLOSED, and a thread the user asked
  to delete must never then be copied into long-lived memory.

OFF unless the manifest says otherwise. Distillation RETAINS derived content for
``memory.retention_days`` (365), so switching it on is a data decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

_SOURCE_KIND = "conversation"
_DEFAULT_IDLE_MINUTES = 60


@dataclass(frozen=True)
class DistillationPolicy:
    """What the manifest asked for. ``enabled`` false means do nothing at all."""

    enabled: bool = False
    idle_after: timedelta = timedelta(minutes=_DEFAULT_IDLE_MINUTES)
    batch: int = 20
    # ingest.incremental, READ since 2026-07-31 (task #43). True: a thread that
    # GREW after its distillation is re-distilled on a later sweep, replacing its
    # summary. False: the pre-#43 behaviour, one summary forever, frozen at the
    # first distillation - which is at least now a choice rather than a defect.
    incremental: bool = True

    @property
    def idle_minutes(self) -> int:
        return int(self.idle_after.total_seconds() // 60)


def policy_from_manifest(extra: dict[str, Any] | None) -> DistillationPolicy:
    """Read ``memory.ingest.on_session_end`` out of the raw manifest section.

    The memory block is carried as raw ``extra``, so this is the first code to give
    the field meaning. Anything missing or malformed yields the OFF default rather
    than a guess: a retention feature must not switch itself on by accident.
    """
    memory = (extra or {}).get("memory")
    if not isinstance(memory, dict) or memory.get("enabled") is False:
        return DistillationPolicy()
    ingest = memory.get("ingest")
    if not isinstance(ingest, dict) or ingest.get("on_session_end") is not True:
        return DistillationPolicy()
    raw = ingest.get("session_idle_minutes", _DEFAULT_IDLE_MINUTES)
    minutes = raw if isinstance(raw, int) and raw > 0 else _DEFAULT_IDLE_MINUTES
    return DistillationPolicy(
        enabled=True,
        idle_after=timedelta(minutes=minutes),
        incremental=ingest.get("incremental") is not False,
    )


async def select_conversations_to_distil(
    store: Any, tenant_id: str, now: Any, policy: DistillationPolicy
) -> list[Any]:
    """Idle, still-open threads that are undistilled - or grew since (task #43).

    The growth predicate lives in the STORE query, not here: filtered in Python
    after the LIMIT, a page of distilled-and-unchanged threads wedges the sweep
    while a grown thread waits beyond it (the 2026-07-30 wedge, again). Receipts
    from before #43 carry no baseline and are settled until
    ``backfill_distillation_baselines`` stamps them (the sweep runs it), which is
    what stops the pre-#43 backlog being re-written wholesale.
    """
    if not policy.enabled:
        return []
    idle_before = now - policy.idle_after
    return await store.list_idle_conversations(
        tenant_id, idle_before, limit=policy.batch, include_grown=policy.incremental
    )


def distillation_context(tenant_id: str, user_id: str) -> Any:
    """The seat ONE distillation acts under: memory.remember, for a single owner.

    ``on_behalf_of`` is load-bearing. ``ultracode_memory.owner_scopes`` derives the
    permitted memory scopes from it, and ``adapter_writes._refuse_unsafe_content``
    rejects a write to any scope outside that set - so a context with no principal
    is refused for EVERY user. Binding the thread's own owner here is what makes
    the write land in that owner's scope, and bounds it to nowhere else.
    """
    from boltrig.models import GrantSet, InvocationContext

    return InvocationContext(
        tenant_id=tenant_id,
        actor="session-distillation",
        actor_tier="system",
        on_behalf_of=user_id,
        # memory.forget joined the seat with #43: a re-distillation REPLACES the
        # thread's prior summary rather than accumulating a second, and the seat
        # that wrote a summary may retire its own. Still bounded to the thread
        # owner's scope by on_behalf_of, exactly as the write is.
        grants=GrantSet.of(["memory.remember", "memory.forget"]),
    )


async def distil_conversation(kernel: Any, tenant_id: str, conv: Any, context: Any) -> bool:
    """Summarise one quiet thread into memory through the governed verb.

    Routed through ``kernel.invoke("memory", "memory.remember", ...)`` rather than
    writing the store directly, because the manifest's ``ingest.screen_content``
    anti-poisoning screen (SEC-42) and the grant check live at that chokepoint. A
    direct store write would be faster and would skip both.

    Returns whether a receipt was written. Best-effort: a thread that fails to
    distil leaves NO receipt, so the next sweep retries it rather than silently
    dropping it.
    """
    from boltrig.fleet.continuity import summarize_messages
    from boltrig.models.memory import MemoryIngestion

    import hashlib

    store = kernel.store
    messages = await store.list_messages(tenant_id, conv.id)
    if not messages:
        return False

    content = summarize_messages(messages)[:2000]
    if not content.strip():
        return False

    prior = await store.get_memory_ingestion_by_source(tenant_id, _SOURCE_KIND, conv.id)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if prior is not None and prior.detail.get("content_sha256") == digest:
        # The thread grew but summarises identically; re-writing 365-day memory
        # with the same bytes is churn, not fidelity. Advance the baseline so
        # this thread is not re-selected every sweep.
        prior.detail["message_count"] = len(messages)
        await store.update_memory_ingestion(prior)
        return False

    owner_scope = f"user:{conv.user_id}"
    if prior is not None:
        # Replace, never accumulate (#43): the old summary is retired FIRST so a
        # crash between the two verbs leaves the thread summary-less and
        # receipt-stale - a state the next sweep repairs - rather than
        # double-summarised, a state nothing detects. By source_ref, not a fact
        # id: it catches summaries written before receipts recorded ids, and the
        # governed verb scope-bounds the erasure to this owner and ledgers it.
        await kernel.invoke(
            "memory", "memory.forget", {"source_ref": conv.id}, context
        )
    result = await kernel.invoke(
        "memory",
        "memory.remember",
        {
            "content": content,
            "owner_scope": owner_scope,
            "kind": "summary",
            "source_kind": _SOURCE_KIND,
            "source_ref": conv.id,
        },
        context,
    )
    del result  # the receipt records counts and content, not engine internals
    # The receipt is written only AFTER the governed write succeeds. Writing it
    # first would mark a thread distilled that the screen had refused. The
    # stable id makes a re-distillation OVERWRITE its receipt, so a thread has
    # exactly one, always describing the latest summary.
    await store.add_memory_ingestion(
        MemoryIngestion(
            id=f"distil-{conv.id}",
            tenant_id=tenant_id,
            source_kind=_SOURCE_KIND,
            source_ref=conv.id,
            owner_scope=owner_scope,
            status="done",
            facts_added=1,
            detail={
                "message_count": len(messages),
                "content_sha256": digest,
            },
        )
    )
    return True


async def run_one_distillation_sweep(
    kernel: Any,
    tenant_id: str,
    policy: DistillationPolicy,
    context_factory: Any,
    now: Any,
    log: Any,
) -> tuple[int, int, int]:
    """One cycle: select, distil each, return (seen, acted, pending).

    Split out of the forever-loop so a single cycle is testable without a task, a
    clock or a cancel - and so the loop itself stays short enough to read, which
    is what the structural ratchet is for.
    """
    if policy.incremental:
        # Stamp pre-#43 receipts with a baseline (bounded batch) so growth
        # becomes detectable, without re-writing the pre-#43 backlog wholesale.
        await kernel.store.backfill_distillation_baselines(
            tenant_id, limit=policy.batch
        )
    due = await select_conversations_to_distil(kernel.store, tenant_id, now, policy)
    # pending comes from a count that shares no logic with selection, so a bug
    # INSIDE selection (the 2026-07-30 wedge filtered every candidate away) cannot
    # also zero this number. Without it, seen=0 acted=0 reports "idle" for a sweep
    # that is in fact stuck.
    pending = await kernel.store.count_pending_distillation(
        tenant_id, now - policy.idle_after
    )
    acted = 0
    for conv in due:
        try:
            # The context is built PER THREAD, on behalf of its owner. A single
            # generic seat cannot work: memory RBAC derives the permitted owner
            # scopes from context.on_behalf_of, so a context with no principal is
            # refused for every user. The check was right; the seat was wrong.
            await distil_conversation(
                kernel, tenant_id, conv, context_factory(conv.user_id)
            )
            acted += 1
        except Exception:  # one bad thread must not stall the rest
            log.exception("distillation failed for conversation %s", conv.id)
    return len(due), acted, pending


async def run_distillation_forever(
    kernel: Any,
    tenant_id: str,
    policy: DistillationPolicy,
    context_factory: Any,
    *,
    interval: float = 300.0,
    now_fn: Any = None,
) -> None:
    """Call ``select_conversations_to_distil`` then ``distil_conversation`` on a slow
    loop, never crashing the worker (P9).

    Same shape as the retention janitor: store-driven, engine-independent, and a
    bad cycle is logged and skipped rather than taking the process down. The
    interval is deliberately slow - the idle window is an hour, so sweeping every
    few minutes is ample and keeps the read off the hot path.
    """
    import asyncio
    import logging

    from boltrig.fleet.sweep_progress import SweepProgress
    from boltrig.models.base import utcnow
    from boltrig.observability.background_jobs import (
        new_background_process_identity,
        record_background_attempt,
    )

    log = logging.getLogger("boltrig.memory.session_distillation")
    clock = now_fn or utcnow
    # Silence was the failure. Every cycle now states what it saw against what it
    # did, so a sweep that can see work and does none is visible in the log rather
    # than only in a database count somebody thought to check.
    progress = SweepProgress("session-distillation")
    # SweepProgress writes to the LOG, which survives no restart and answers no
    # operator query. The durable half is the background-job receipt ledger, which
    # /readyz already reads for the retention and hitl_expiry janitors - so this
    # loop now records there too rather than inventing a third mechanism.
    identity = new_background_process_identity()
    while True:
        attempted_at = clock()
        succeeded = True
        try:
            seen, acted, pending = await run_one_distillation_sweep(
                kernel, tenant_id, policy, context_factory, clock(), log
            )
            progress.record(seen=seen, acted=acted, pending=pending)
        except asyncio.CancelledError:
            raise
        except Exception:
            succeeded = False
            acted = 0
            log.exception("distillation sweep failed; continuing")
        # Best-effort evidence, exactly as the retention janitor does it: it can
        # never change the sweep outcome, and a failed write must not stall the
        # loop. This is the DURABLE half - SweepProgress logs, which survive no
        # restart and answer no operator query.
        await record_background_attempt(
            kernel.store,
            tenant_id=tenant_id,
            job_name="distillation",
            process_instance_identity=identity,
            interval_seconds=interval,
            attempted_at=attempted_at,
            succeeded=succeeded,
            item_count=acted,
        )
        await asyncio.sleep(interval)
