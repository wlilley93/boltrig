"""`ingest.incremental` is READ (task #43): a grown thread is re-distilled.

Before this, a thread was distilled ONCE and never revisited, so a conversation
that continued after distillation kept a summary of only its earlier messages -
in 365-day memory, presented as the thread's summary. The flag the manifest
already shipped for this governs it now, and a re-distillation REPLACES the old
summary rather than accumulating a second.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from boltrig.memory.session_distillation import (
    distil_conversation,
    distillation_context,
    policy_from_manifest,
    select_conversations_to_distil,
)
from boltrig.models.conversation import Conversation, ConversationStatus
from boltrig.models.memory import MemoryIngestion
from boltrig.store import InMemoryStore

pytestmark = pytest.mark.unit

T = "t-redistil"
NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


def _manifest(**ingest):
    return {"memory": {"enabled": True, "ingest": {"on_session_end": True, **ingest}}}


async def _conv(store, conv_id, *, minutes_idle=90):
    conv = Conversation(
        id=conv_id,
        tenant_id=T,
        user_id="u1",
        title=conv_id,
        status=ConversationStatus.ACTIVE,
        created_at=NOW - timedelta(days=1),
        updated_at=NOW - timedelta(minutes=minutes_idle),
    )
    store._convs[(T, conv_id)] = conv
    return conv


async def _messages(store, conv_id, texts):
    from boltrig.models.conversation import ConversationMessage, MessageRole

    start = len(await store.list_messages(T, conv_id))
    for i, text in enumerate(texts, start=start):
        await store.add_message(
            ConversationMessage(
                id=f"{conv_id}-m{i}",
                conversation_id=conv_id,
                tenant_id=T,
                role=MessageRole.USER,
                content=text,
            )
        )


def _receipt(conv_id, *, detail=None):
    return MemoryIngestion(
        id=f"distil-{conv_id}",
        tenant_id=T,
        source_kind="conversation",
        source_ref=conv_id,
        owner_scope="user:u1",
        status="done",
        detail=dict(detail or {}),
    )


class _Kernel:
    """Records governed invocations; the store is the real InMemoryStore."""

    def __init__(self, store) -> None:
        self.store = store
        self.calls: list[tuple[str, dict]] = []

    async def invoke(self, noun, verb, params, context, **_kw):
        self.calls.append((verb, params))
        return {"fact_ids": [f"fact-{len(self.calls)}"]}


# --- selection -------------------------------------------------------------


async def test_a_thread_that_grew_after_distillation_is_reselected() -> None:
    store = InMemoryStore()
    conv = await _conv(store, "grew")
    await _messages(store, "grew", ["a", "b", "c"])
    await store.add_memory_ingestion(_receipt("grew", detail={"message_count": 2}))

    policy = policy_from_manifest(_manifest())
    picked = await select_conversations_to_distil(store, T, NOW, policy)
    assert [c.id for c in picked] == [conv.id], "3 > 2: the thread grew"


async def test_an_unchanged_distilled_thread_stays_skipped() -> None:
    store = InMemoryStore()
    await _conv(store, "same")
    await _messages(store, "same", ["a", "b"])
    await store.add_memory_ingestion(_receipt("same", detail={"message_count": 2}))

    picked = await select_conversations_to_distil(
        store, T, NOW, policy_from_manifest(_manifest())
    )
    assert picked == []


async def test_incremental_false_freezes_at_the_first_summary_by_choice() -> None:
    """The pre-#43 behaviour survives as a CHOICE: false means one summary
    forever, and the manifest says so instead of a defect doing it silently."""
    store = InMemoryStore()
    await _conv(store, "frozen")
    await _messages(store, "frozen", ["a", "b", "c", "d"])
    await store.add_memory_ingestion(_receipt("frozen", detail={"message_count": 1}))

    picked = await select_conversations_to_distil(
        store, T, NOW, policy_from_manifest(_manifest(incremental=False))
    )
    assert picked == []
    assert policy_from_manifest(_manifest()).incremental is True, "absent means true"


async def test_a_pre43_receipt_is_baselined_not_reprocessed() -> None:
    """The backlog protection. A receipt from before #43 has no message_count;
    re-distilling all of those in one sweep would re-write 365-day memory
    wholesale (89 threads on the beelink). Instead the CURRENT count becomes the
    baseline, recorded on the receipt, and growth is detectable from then on."""
    store = InMemoryStore()
    await _conv(store, "legacy")
    await _messages(store, "legacy", ["a", "b", "c"])
    await store.add_memory_ingestion(_receipt("legacy"))  # no message_count

    policy = policy_from_manifest(_manifest())
    # Without a baseline the receipt SETTLES the thread (no wholesale rewrite)...
    assert await select_conversations_to_distil(store, T, NOW, policy) == []
    # ...and the sweep's backfill stamps the baseline, exactly as
    # run_one_distillation_sweep does before selecting.
    assert await store.backfill_distillation_baselines(T, limit=50) == 1
    receipt = await store.get_memory_ingestion_by_source(T, "conversation", "legacy")
    assert receipt.detail["message_count"] == 3, "the baseline must be recorded"

    # ...and growth past the recorded baseline IS picked up next sweep.
    await _messages(store, "legacy", ["d"])
    picked = await select_conversations_to_distil(store, T, NOW, policy)
    assert [c.id for c in picked] == ["legacy"]


# --- the re-distillation itself -------------------------------------------


async def test_redistillation_replaces_the_old_summary_never_accumulates() -> None:
    """forget(source_ref) FIRST, then remember: a crash between the two leaves
    the thread summary-less and receipt-stale - a state the next sweep repairs -
    rather than double-summarised, a state nothing detects."""
    store = InMemoryStore()
    conv = await _conv(store, "replace")
    await _messages(store, "replace", ["hello", "world"])
    await store.add_memory_ingestion(
        _receipt("replace", detail={"message_count": 1, "content_sha256": "old"})
    )

    kernel = _Kernel(store)
    context = distillation_context(T, "u1")
    assert await distil_conversation(kernel, T, conv, context) is True

    verbs = [verb for verb, _ in kernel.calls]
    assert verbs == ["memory.forget", "memory.remember"], verbs
    forget_params = kernel.calls[0][1]
    assert forget_params == {"source_ref": conv.id}, (
        "by source_ref, so summaries written before receipts recorded ids are "
        "retired too"
    )
    receipt = await store.get_memory_ingestion_by_source(T, "conversation", conv.id)
    assert receipt.detail["message_count"] == 2, "the receipt must advance"
    assert receipt.detail["content_sha256"] != "old"


async def test_a_first_distillation_never_calls_forget() -> None:
    """The negative control: forget-first must not fire for a thread with no
    prior summary - an erasure of nothing is noise in the erasure ledger."""
    store = InMemoryStore()
    conv = await _conv(store, "fresh")
    await _messages(store, "fresh", ["hi"])

    kernel = _Kernel(store)
    assert await distil_conversation(kernel, T, conv, distillation_context(T, "u1")) is True
    assert [verb for verb, _ in kernel.calls] == ["memory.remember"]


async def test_identical_content_advances_the_baseline_without_rewriting() -> None:
    """A thread can grow by messages the summariser ignores. Re-writing 365-day
    memory with the same bytes is churn, not fidelity - so the baseline advances
    and nothing is written."""
    import hashlib

    from boltrig.fleet.continuity import summarize_messages

    store = InMemoryStore()
    conv = await _conv(store, "same-bytes")
    await _messages(store, "same-bytes", ["alpha", "beta"])
    messages = await store.list_messages(T, conv.id)
    digest = hashlib.sha256(
        summarize_messages(messages)[:2000].encode("utf-8")
    ).hexdigest()
    await store.add_memory_ingestion(
        _receipt("same-bytes", detail={"message_count": 1, "content_sha256": digest})
    )

    kernel = _Kernel(store)
    assert await distil_conversation(kernel, T, conv, distillation_context(T, "u1")) is False
    assert kernel.calls == [], "no governed write for identical content"
    receipt = await store.get_memory_ingestion_by_source(T, "conversation", conv.id)
    assert receipt.detail["message_count"] == 2, "but the baseline still advances"


async def test_a_continued_thread_counts_as_pending_again() -> None:
    """#43's half of the pending contract, in the receipt-note's own words: a
    thread is settled by a receipt NEWER than its last message, not by any
    receipt at all. Without this, a continued thread sits in both counts and
    pending reads 0 while one genuinely waits - the exact blind spot the count
    was added to close, reopened."""
    from datetime import timedelta

    store = InMemoryStore()
    # Distilled, then the user CONTINUED the thread: last message after receipt.
    conv = await _conv(store, "continued", minutes_idle=90)
    receipt = _receipt("continued", detail={"message_count": 1})
    receipt.created_at = conv.updated_at - timedelta(hours=2)
    await store.add_memory_ingestion(receipt)
    # And a settled one: receipt newer than the last message.
    conv2 = await _conv(store, "settled", minutes_idle=90)
    receipt2 = _receipt("settled", detail={"message_count": 1})
    receipt2.created_at = conv2.updated_at + timedelta(minutes=5)
    await store.add_memory_ingestion(receipt2)

    idle_before = NOW - timedelta(minutes=60)
    assert await store.count_pending_distillation(T, idle_before) == 1
