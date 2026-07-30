"""Long-conversation compaction - append-only derived summaries (SEC-90..93).

Past a threshold the continuity composer sends [derived summary of older turns] +
[recent verbatim tail] instead of the whole history, so a long conversation stays
cheap. The summary is DERIVED data, never a mutation of the frozen message record
([2026] VJS-COUNTY 4 froze message content). These bind the load-bearing
guarantees:

  SEC-90  compaction never mutates a frozen message - it only INSERTS a derived
          conversation_summaries row; the append-only message history is intact.
  SEC-91  the compacted composition preserves prefix-stability across turns until
          the next compaction (turn N's task is a byte-prefix of turn N+1's), so
          the gateway prompt cache keeps hitting.
  SEC-92  superseded turns stay excluded after compaction - a regenerated-away
          reply is neither summarised into the summary nor present in the tail.
  SEC-93  below the threshold the composition is unchanged (full verbatim history,
          identical to the pre-compaction continuity render).
  FR-CONV-08 the owner-facing conversation projection describes the exact summary
          boundary and recent verbatim tail used by the next model turn.
"""

from __future__ import annotations

import pytest

from boltrig.config.manifest import ChatConfig
from boltrig.fleet.chat import ChatService
from boltrig.fleet.continuity import compose_turn_task, render_transcript
from boltrig.kernel.events import EventRelay
from boltrig.models import (
    Conversation,
    ConversationMessage,
    ConversationStatus,
    ConversationSummary,
    MessageRole,
)
from boltrig.store import InMemoryStore

T = "acme"
CID = "conv-1"


def _msg(mid: str, role: MessageRole, content: str) -> ConversationMessage:
    return ConversationMessage(
        id=mid, conversation_id=CID, tenant_id=T, role=role, content=content
    )


async def _seed_conversation(store: InMemoryStore, contents: list[tuple[MessageRole, str]]):
    await store.create_conversation(
        Conversation(id=CID, tenant_id=T, user_id="alice", status=ConversationStatus.ACTIVE)
    )
    msgs = [_msg(f"m{i}", role, text) for i, (role, text) in enumerate(contents)]
    for m in msgs:
        await store.add_message(m)
    return msgs


def _alternating(n: int) -> list[tuple[MessageRole, str]]:
    """n turns => 2n messages, each with a unique probe content."""
    out: list[tuple[MessageRole, str]] = []
    for i in range(n):
        out.append((MessageRole.USER, f"user-probe-{i}"))
        out.append((MessageRole.ASSISTANT, f"assistant-probe-{i}"))
    return out


# --------------------------------------------------------------------------- #
# SEC-90  compaction is append-only derived data; it never mutates a message
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-90")
async def test_compaction_never_mutates_a_frozen_message():
    store = InMemoryStore()
    msgs = await _seed_conversation(store, _alternating(3))  # 6 messages
    cfg = ChatConfig(compaction_threshold=4, compaction_keep_recent=2)
    chat = ChatService(store, EventRelay(), chat_config=cfg)

    before = [
        (m.id, m.role, m.content, m.superseded_by)
        for m in await store.list_messages(T, CID)
    ]
    assert await store.get_latest_conversation_summary(T, CID) is None

    await chat._maybe_compact(T, CID)

    after_msgs = await store.list_messages(T, CID)
    after = [(m.id, m.role, m.content, m.superseded_by) for m in after_msgs]
    # Every message is byte-for-byte intact: none added, removed, edited or marked.
    assert after == before
    assert len(after_msgs) == len(msgs)
    assert all(m.superseded_by is None for m in after_msgs)

    # The ONLY new state is a derived summary row covering the older turns.
    summary = await store.get_latest_conversation_summary(T, CID)
    assert isinstance(summary, ConversationSummary)
    assert summary.covered_count == 4  # 6 live - keep_recent(2)
    assert summary.up_to_message_id == "m3"
    # It is DERIVED text, not a copy of a message row identity.
    assert summary.id not in {m.id for m in after_msgs}


# --------------------------------------------------------------------------- #
# SEC-91  the compacted composition is prefix-stable across turns
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-91")
def test_compacted_composition_is_prefix_stable_until_next_compaction():
    cfg = ChatConfig(compaction_threshold=4, compaction_keep_recent=2)
    # A fixed summary covering m0..m3 (boundary = m3). The tail is everything after.
    summary = ConversationSummary(
        id="s1", conversation_id=CID, tenant_id=T,
        up_to_message_id="m3", covered_count=4, summary="OLD-TURNS-DIGEST",
    )
    live_n = [_msg(f"m{i}", MessageRole.USER if i % 2 == 0 else MessageRole.ASSISTANT,
                   f"probe-{i}") for i in range(6)]  # m0..m5, tail = m4,m5
    task_n = compose_turn_task(live_n, "ignored", summary=summary, config=cfg)

    # Turn N+1 APPENDS a new user message; the same fixed summary still applies.
    live_n1 = live_n + [_msg("m6", MessageRole.USER, "probe-6")]
    task_n1 = compose_turn_task(live_n1, "ignored", summary=summary, config=cfg)

    # Prefix stability: N's whole task is a byte-prefix of N+1's (gateway cache).
    assert task_n1.startswith(task_n)
    assert task_n1 != task_n
    # The summary block replaced the older turns; only the tail is verbatim.
    assert "OLD-TURNS-DIGEST" in task_n
    assert "probe-0" not in task_n and "probe-3" not in task_n  # summarised away
    assert "probe-4" in task_n and "probe-5" in task_n           # verbatim tail
    assert "probe-6" in task_n1 and "probe-6" not in task_n      # appended, not before


# --------------------------------------------------------------------------- #
# SEC-92  superseded turns stay excluded after compaction
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-92")
async def test_superseded_turns_stay_excluded_after_compaction():
    store = InMemoryStore()
    # An older assistant reply is superseded (a regenerate replaced it). Its body
    # carries a probe that must never survive compaction anywhere.
    contents = [
        (MessageRole.USER, "user-probe-0"),
        (MessageRole.ASSISTANT, "SUPERSEDED-SECRET-A0"),
        (MessageRole.USER, "user-probe-1"),
        (MessageRole.ASSISTANT, "assistant-probe-1"),
        (MessageRole.USER, "user-probe-2"),
        (MessageRole.ASSISTANT, "assistant-probe-2"),
    ]
    await _seed_conversation(store, contents)
    await store.mark_message_superseded(T, "m1", "regen-x")  # supersede the older reply

    cfg = ChatConfig(compaction_threshold=4, compaction_keep_recent=2)
    chat = ChatService(store, EventRelay(), chat_config=cfg)
    await chat._maybe_compact(T, CID)

    summary = await store.get_latest_conversation_summary(T, CID)
    assert summary is not None
    # The superseded reply was NOT summarised into the derived text.
    assert "SUPERSEDED-SECRET-A0" not in summary.summary
    # live = 5 (m1 filtered); older = live[:-2] = 3 turns -> boundary is m3.
    assert summary.covered_count == 3
    assert summary.up_to_message_id == "m3"

    # And it is absent from the composed task: neither summarised nor in the tail.
    messages = await store.list_messages(T, CID)
    task = compose_turn_task(messages, "next", summary=summary, config=cfg)
    assert "SUPERSEDED-SECRET-A0" not in task
    assert "user-probe-2" in task and "assistant-probe-2" in task  # verbatim tail


# --------------------------------------------------------------------------- #
# SEC-93  below the threshold the composition is unchanged (full verbatim)
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-93")
def test_below_threshold_composition_is_unchanged():
    cfg = ChatConfig(compaction_threshold=40, compaction_keep_recent=12)
    live = [_msg(f"m{i}", MessageRole.USER if i % 2 == 0 else MessageRole.ASSISTANT,
                 f"probe-{i}") for i in range(4)]  # 4 << threshold
    # Even with a summary available, a below-threshold thread renders full verbatim,
    # byte-identical to the no-summary continuity render (pre-compaction behaviour).
    summary = ConversationSummary(
        id="s", conversation_id=CID, tenant_id=T,
        up_to_message_id="m1", covered_count=2, summary="SHOULD-NOT-APPEAR",
    )
    with_summary = compose_turn_task(live, "x", summary=summary, config=cfg)
    plain = compose_turn_task(live, "x")
    assert with_summary == plain == render_transcript(live)
    assert "SHOULD-NOT-APPEAR" not in with_summary

    # Compaction disabled (threshold 0) is always the full verbatim render too.
    off = ChatConfig(compaction_threshold=0, compaction_keep_recent=0)
    big = [_msg(f"m{i}", MessageRole.USER, f"p{i}") for i in range(50)]
    assert compose_turn_task(big, "x", summary=summary, config=off) == render_transcript(big)


# --------------------------------------------------------------------------- #
# FR-CONV-08  the owner can inspect the exact model-context compaction boundary
# --------------------------------------------------------------------------- #
@pytest.mark.invariant("FR-CONV-08")
async def test_compaction_view_matches_the_exact_next_turn_boundary():
    store = InMemoryStore()
    messages = await _seed_conversation(store, _alternating(3))
    cfg = ChatConfig(compaction_threshold=4, compaction_keep_recent=2)
    chat = ChatService(store, EventRelay(), chat_config=cfg)
    await chat._maybe_compact(T, CID)

    summary = await store.get_latest_conversation_summary(T, CID)
    assert summary is not None
    view = await chat.context_compaction_view(T, CID, messages)

    assert view == {
        "compacted": True,
        "covered_count": 4,
        "recent_exact_count": 2,
        "up_to_message_id": "m3",
        "summary": summary.summary,
    }
    task = compose_turn_task(messages, "ignored", summary=summary, config=cfg)
    assert summary.summary in task
    assert "user-probe-2" in task
    assert "assistant-probe-2" in task
    # The covered probe occurs once inside the summary, never a second time as
    # verbatim transcript text; the recent probes are the exact tail.
    assert task.count("user-probe-0") == 1


@pytest.mark.invariant("FR-CONV-08")
async def test_compaction_view_is_honestly_inactive_without_a_usable_boundary():
    store = InMemoryStore()
    messages = await _seed_conversation(store, _alternating(1))
    chat = ChatService(
        store,
        EventRelay(),
        chat_config=ChatConfig(compaction_threshold=4, compaction_keep_recent=2),
    )

    assert await chat.context_compaction_view(T, CID, messages) == {
        "compacted": False,
        "covered_count": 0,
        "recent_exact_count": 2,
        "up_to_message_id": None,
        "summary": None,
    }
