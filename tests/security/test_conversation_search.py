"""Owner-scoped conversation search (US-CONV-10, SEC-94/95/96).

``search_conversations`` is a case-insensitive substring match over the CALLER'S
OWN conversation titles + LIVE (non-superseded) message content, paginated and
fail-closed to the caller's scope:

  - SEC-94: it is owner-scoped - another user's conversation is NEVER returned,
    even one whose title/messages match the same term.
  - SEC-95: a superseded turn ([2026] VJS-COUNTY 4) never surfaces as a live match
    (mirrors the continuity filtering); the same term in a LIVE message does.
  - SEC-96: the query is a bound parameter with LIKE metacharacters escaped, so a
    caller cannot turn a search term into a wildcard (``%`` is a literal, not
    match-anything) - there is no SQL/wildcard injection surface.

Proven on BOTH stores (parity): in-memory everywhere, Postgres when
BOLTRIG_TEST_DATABASE_URL is set (skips cleanly offline).
"""

from __future__ import annotations

import os

import pytest

from boltrig.models import (
    Conversation,
    ConversationMessage,
    ConversationStatus,
    MessageRole,
    utcnow,
)

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


async def _conv(store, cid, user, title):
    await store.create_conversation(
        Conversation(
            id=cid, tenant_id=T, user_id=user, title=title,
            status=ConversationStatus.ACTIVE,
        )
    )


async def _msg(store, mid, cid, content, *, role=MessageRole.USER, superseded_by=None):
    await store.add_message(
        ConversationMessage(
            id=mid, conversation_id=cid, tenant_id=T, role=role,
            content=content, superseded_by=superseded_by, created_at=utcnow(),
        )
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-94")
async def test_search_is_owner_scoped_never_returns_another_users_conversation(store):
    # alice and bob both have a "budget" thread in the same tenant.
    await _conv(store, "a1", "alice", "Q3 budget plan")
    await _conv(store, "b1", "bob", "bob's budget secrets")
    await _msg(store, "b1m", "b1", "the budget numbers are 42")
    results, nxt = await store.search_conversations(T, "alice", "budget", limit=50)
    ids = {c.id for c, _ in results}
    assert ids == {"a1"}  # only alice's own; bob's never surfaces
    assert all(c.user_id == "alice" for c, _ in results)
    assert nxt is None


@pytest.mark.security
@pytest.mark.invariant("SEC-94")
async def test_search_matches_title_and_live_message_with_snippet(store):
    await _conv(store, "a1", "alice", "planning")           # title miss
    await _msg(store, "a1m", "a1", "let us discuss the WIDGET rollout")  # message hit
    await _conv(store, "a2", "alice", "widget design")      # title hit
    results, _ = await store.search_conversations(T, "alice", "widget", limit=50)
    by_id = {c.id: snippet for c, snippet in results}
    assert set(by_id) == {"a1", "a2"}
    # message-only match carries the matched live content as its snippet;
    assert by_id["a1"] is not None and "WIDGET" in by_id["a1"]
    # title-only match has no message snippet (mirrors the in-memory contract).
    assert by_id["a2"] is None


@pytest.mark.security
@pytest.mark.invariant("SEC-95")
async def test_superseded_message_is_not_a_live_search_hit(store):
    await _conv(store, "a1", "alice", "regen thread")
    # the old reply mentioning "pineapple" was superseded by a newer turn
    await _msg(store, "old", "a1", "the answer is pineapple", superseded_by="new")
    await _msg(store, "new", "a1", "the answer is mango")
    # searching the superseded-only term yields nothing (frozen, never live)
    superseded_hits, _ = await store.search_conversations(T, "alice", "pineapple", limit=50)
    assert superseded_hits == []
    # the live term still matches
    live_hits, _ = await store.search_conversations(T, "alice", "mango", limit=50)
    assert [c.id for c, _ in live_hits] == ["a1"]


@pytest.mark.security
@pytest.mark.invariant("SEC-96")
async def test_like_metacharacters_are_escaped_not_wildcards(store):
    await _conv(store, "a1", "alice", "alpha")
    await _conv(store, "a2", "alice", "beta")
    await _conv(store, "a3", "alice", "50%_done")  # literal % and _ in the title
    # a bare "%" must NOT act as match-anything (no injection/wildcard surface):
    wild, _ = await store.search_conversations(T, "alice", "%", limit=50)
    assert [c.id for c, _ in wild] == ["a3"]  # only the row literally containing '%'
    # "_" is likewise a literal, not the single-char wildcard
    under, _ = await store.search_conversations(T, "alice", "%_done", limit=50)
    assert [c.id for c, _ in under] == ["a3"]


@pytest.mark.security
@pytest.mark.invariant("SEC-94")
async def test_search_results_are_paginated_and_bounded(store):
    for i in range(5):
        await _conv(store, f"a{i}", "alice", f"report {i}")
    page1, nxt1 = await store.search_conversations(T, "alice", "report", limit=2, offset=0)
    assert len(page1) == 2 and nxt1 == 2
    page2, nxt2 = await store.search_conversations(T, "alice", "report", limit=2, offset=nxt1)
    assert len(page2) == 2 and nxt2 == 4
    page3, nxt3 = await store.search_conversations(T, "alice", "report", limit=2, offset=nxt2)
    assert len(page3) == 1 and nxt3 is None
