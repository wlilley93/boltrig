"""Conversation list pagination (US-CONV-09, FR-CONV-07).

``list_conversations_page`` returns one bounded, stably-ordered page (updated_at
DESC with an id ASC tiebreak) plus the next offset (None once exhausted), while the
original unpaginated ``list_conversations`` is untouched. The page size is a
ChatConfig ceiling: a caller-supplied limit is clamped DOWN, None falls back to the
conservative default, so an unbounded scan is impossible. Proven on BOTH stores
(parity): the in-memory store everywhere, Postgres when BOLTRIG_TEST_DATABASE_URL is
set (skips cleanly offline).
"""

from __future__ import annotations

import os
from datetime import timedelta

import pytest

from boltrig.config.manifest import (
    DEFAULT_CONVERSATION_MAX_PAGE_SIZE,
    DEFAULT_CONVERSATION_PAGE_SIZE,
    ChatConfig,
)
from boltrig.models import Conversation, ConversationStatus, utcnow

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
T = "acme"
_TABLES = "conversations,conversation_messages"


async def _make_store(kind: str):
    if kind == "memory":
        from boltrig.store import InMemoryStore

        return InMemoryStore()
    from boltrig.store import PostgresStore

    store = await PostgresStore.connect(DSN)
    await store._pool.execute(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE")
    return store


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(
                DSN is None, reason="BOLTRIG_TEST_DATABASE_URL not set"
            ),
        ),
    ]
)
async def store(request):
    return await _make_store(request.param)


async def _seed(store, user: str, n: int):
    # Distinct, monotonically INCREASING updated_at so the newest is deterministic;
    # ids are zero-padded so the id ASC tiebreak is easy to assert.
    base = utcnow()
    for i in range(n):
        await store.create_conversation(
            Conversation(
                id=f"{user}-c{i:03d}", tenant_id=T, user_id=user,
                title=f"thread {i}", status=ConversationStatus.ACTIVE,
                created_at=base, updated_at=base + timedelta(seconds=i),
            )
        )


@pytest.mark.invariant("FR-CONV-07")
async def test_page_is_stable_ordered_and_next_offset_walks_to_exhaustion(store):
    await _seed(store, "alice", 5)
    # newest-first: c004, c003, c002, c001, c000
    page1, nxt1 = await store.list_conversations_page(T, "alice", limit=2, offset=0)
    assert [c.id for c in page1] == ["alice-c004", "alice-c003"]
    assert nxt1 == 2
    page2, nxt2 = await store.list_conversations_page(T, "alice", limit=2, offset=nxt1)
    assert [c.id for c in page2] == ["alice-c002", "alice-c001"]
    assert nxt2 == 4
    page3, nxt3 = await store.list_conversations_page(T, "alice", limit=2, offset=nxt2)
    assert [c.id for c in page3] == ["alice-c000"]
    assert nxt3 is None  # exhausted


@pytest.mark.invariant("FR-CONV-07")
async def test_id_tiebreak_is_deterministic_for_equal_updated_at(store):
    base = utcnow()
    for cid in ("alice-b", "alice-a", "alice-c"):
        await store.create_conversation(
            Conversation(
                id=cid, tenant_id=T, user_id="alice", title="tie",
                status=ConversationStatus.ACTIVE, created_at=base, updated_at=base,
            )
        )
    page, nxt = await store.list_conversations_page(T, "alice", limit=10, offset=0)
    # equal updated_at => id ASC tiebreak, so ordering is deterministic across runs
    assert [c.id for c in page] == ["alice-a", "alice-b", "alice-c"]
    assert nxt is None


@pytest.mark.invariant("FR-CONV-07")
async def test_page_is_owner_scoped(store):
    await _seed(store, "alice", 2)
    await _seed(store, "bob", 3)
    page, _ = await store.list_conversations_page(T, "alice", limit=50, offset=0)
    assert {c.id for c in page} == {"alice-c000", "alice-c001"}
    assert all(c.user_id == "alice" for c in page)


@pytest.mark.invariant("FR-CONV-07")
async def test_unpaginated_list_still_returns_everything(store):
    await _seed(store, "alice", 4)
    convs = await store.list_conversations(T, "alice")
    assert [c.id for c in convs] == [
        "alice-c003", "alice-c002", "alice-c001", "alice-c000"
    ]


@pytest.mark.invariant("FR-CONV-07")
def test_config_clamps_page_size_under_the_max_ceiling():
    cfg = ChatConfig()
    # a huge caller-supplied limit is clamped DOWN to the hard ceiling
    assert cfg.resolve_page_size(10_000) == DEFAULT_CONVERSATION_MAX_PAGE_SIZE
    # None => the conservative default
    assert cfg.resolve_page_size(None) == DEFAULT_CONVERSATION_PAGE_SIZE
    # a page never degenerates to zero rows (would stall pagination)
    assert cfg.resolve_page_size(0) == 1
    assert cfg.resolve_page_size(-5) == 1
    # a tightened manifest may only LOWER the ceiling, never raise it
    tight = ChatConfig(conversation_max_page_size=10, conversation_page_size=10)
    assert tight.resolve_page_size(9_999) == 10
