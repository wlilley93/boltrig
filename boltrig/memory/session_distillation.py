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
    return DistillationPolicy(enabled=True, idle_after=timedelta(minutes=minutes))


async def already_distilled(store: Any, tenant_id: str, conversation_id: str) -> bool:
    """Whether this thread has an ingestion receipt already."""
    existing = await store.get_memory_ingestion_by_source(
        tenant_id, _SOURCE_KIND, conversation_id
    )
    return existing is not None


async def select_conversations_to_distil(
    store: Any, tenant_id: str, now: Any, policy: DistillationPolicy
) -> list[Any]:
    """Idle, still-open threads that have not been distilled yet."""
    if not policy.enabled:
        return []
    idle_before = now - policy.idle_after
    candidates = await store.list_idle_conversations(
        tenant_id, idle_before, limit=policy.batch
    )
    out = []
    for conv in candidates:
        if not await already_distilled(store, tenant_id, conv.id):
            out.append(conv)
    return out


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

    store = kernel.store
    messages = await store.list_messages(tenant_id, conv.id)
    if not messages:
        return False

    content = summarize_messages(messages)[:2000]
    if not content.strip():
        return False

    owner_scope = f"user:{conv.user_id}"
    await kernel.invoke(
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
    # The receipt is written only AFTER the governed write succeeds. Writing it
    # first would mark a thread distilled that the screen had refused.
    await store.add_memory_ingestion(
        MemoryIngestion(
            id=f"distil-{conv.id}",
            tenant_id=tenant_id,
            source_kind=_SOURCE_KIND,
            source_ref=conv.id,
            owner_scope=owner_scope,
            status="done",
            facts_added=1,
        )
    )
    return True


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

    from boltrig.models.base import utcnow

    log = logging.getLogger("boltrig.memory.session_distillation")
    clock = now_fn or utcnow
    while True:
        try:
            due = await select_conversations_to_distil(
                kernel.store, tenant_id, clock(), policy
            )
            for conv in due:
                try:
                    await distil_conversation(
                        kernel, tenant_id, conv, context_factory()
                    )
                except Exception:  # one bad thread must not stall the rest
                    log.exception("distillation failed for conversation %s", conv.id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("distillation sweep failed; continuing")
        await asyncio.sleep(interval)
