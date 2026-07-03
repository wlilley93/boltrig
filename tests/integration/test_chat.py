"""The conversational layer: streaming, persistence, inline HITL (Epic CONV)."""

import pytest
from fastapi.testclient import TestClient

from boltrig.fleet.chat import ChatService
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.kernel.events import EventRelay
from boltrig.store import InMemoryStore

T = "acme"


def _stub_executor(events):
    async def executor(*, run_id, relay, **kw):
        for ev in events:
            relay.publish(run_id, ev)  # ChatService closes the stream afterwards

    return executor


async def _collect(gen):
    return [e async for e in gen]


@pytest.mark.invariant("FR-CONV-04")
async def test_chat_streams_events_and_persists():
    store, relay = InMemoryStore(), EventRelay()
    events = [
        {"type": "reasoning_delta", "delta": "thinking"},
        {"type": "tool_call", "verb": "ticket.create", "input": {}, "status": "running"},
        {"type": "tool_result", "verb": "ticket.create", "status": "ok", "output": {"id": "1"}},
        {"type": "subagent", "child_run_id": "c1", "task": "decompose", "skills": ["a"]},
        {"type": "text_delta", "delta": "Created ticket 1."},
    ]
    chat = ChatService(store, relay, turn_executor=_stub_executor(events))
    out = await _collect(
        chat.handle_turn(tenant_id=T, user_id="alice", role="engineer", message="make a ticket")
    )
    types = [e["type"] for e in out]
    assert types[0] == "message_start" and types[-1] == "message_end"
    assert "tool_call" in types and "subagent" in types
    # persisted: one conversation, user + assistant messages (US-CONV-05)
    convs = await store.list_conversations(T, "alice")
    assert len(convs) == 1
    msgs = await store.list_messages(T, convs[0].id)
    assert [m.role.value for m in msgs] == ["user", "assistant"]
    assert msgs[1].content == "Created ticket 1."


@pytest.mark.invariant("FR-CONV-04")
async def test_inline_hitl_event_streams_and_is_recorded():
    store, relay = InMemoryStore(), EventRelay()
    events = [{"type": "hitl", "hitl_request_id": "h1", "kind": "approval",
               "question": "approve?", "options": ["approve", "reject"]}]
    chat = ChatService(store, relay, turn_executor=_stub_executor(events))
    out = await _collect(
        chat.handle_turn(tenant_id=T, user_id="bob", role="engineer", message="risky")
    )
    assert any(e["type"] == "hitl" and e["hitl_request_id"] == "h1" for e in out)
    convs = await store.list_conversations(T, "bob")
    msgs = await store.list_messages(T, convs[0].id)
    assert msgs[1].hitl_request_id == "h1"  # the inline HITL is recorded on the turn


def test_chat_http_streams_sse():
    store, relay = InMemoryStore(), EventRelay()
    chat = ChatService(store, relay, turn_executor=_stub_executor(
        [{"type": "text_delta", "delta": "hi there"}]
    ))
    client = TestClient(create_app(Kernel(store), chat_service=chat))
    hdr = {"x-boltrig-tenant": T, "x-boltrig-subject": "alice", "x-boltrig-role": "engineer"}
    r = client.post("/v1/chat", json={"message": "hello"}, headers=hdr)
    assert r.status_code == 200
    assert "message_start" in r.text and "hi there" in r.text and "message_end" in r.text
    convs = client.get("/v1/conversations", headers=hdr).json()["conversations"]
    assert len(convs) == 1


async def _seed_conv(store, cid, user, title):
    from datetime import timedelta

    from boltrig.models import Conversation, ConversationStatus, utcnow
    base = utcnow()
    # id encodes ordinal so newest-first is deterministic in the assertions
    await store.create_conversation(
        Conversation(
            id=cid, tenant_id=T, user_id=user, title=title,
            status=ConversationStatus.ACTIVE, created_at=base,
            updated_at=base + timedelta(seconds=int(cid[-1])),
        )
    )


@pytest.mark.invariant("FR-CONV-07")
async def test_http_conversation_list_is_backward_compatible_and_paginates():
    store, relay = InMemoryStore(), EventRelay()
    for i in range(3):
        await _seed_conv(store, f"c{i}", "alice", f"thread {i}")
    client = TestClient(create_app(Kernel(store), chat_service=ChatService(store, relay)))
    hdr = {"x-boltrig-tenant": T, "x-boltrig-subject": "alice", "x-boltrig-role": "engineer"}
    # bare call: unchanged shape, every conversation, no next_offset key
    body = client.get("/v1/conversations", headers=hdr).json()
    assert [c["id"] for c in body["conversations"]] == ["c2", "c1", "c0"]
    assert "next_offset" not in body
    # opt into pagination: one bounded page + a next offset that walks to exhaustion
    p1 = client.get("/v1/conversations?limit=2", headers=hdr).json()
    assert [c["id"] for c in p1["conversations"]] == ["c2", "c1"]
    assert p1["next_offset"] == 2
    p2 = client.get("/v1/conversations?limit=2&offset=2", headers=hdr).json()
    assert [c["id"] for c in p2["conversations"]] == ["c0"]
    assert p2["next_offset"] is None


@pytest.mark.invariant("SEC-94")
async def test_http_conversation_search_is_owner_scoped():
    store, relay = InMemoryStore(), EventRelay()
    await _seed_conv(store, "a0", "alice", "budget review")
    await _seed_conv(store, "b0", "bob", "budget secrets")  # another user, same term
    client = TestClient(create_app(Kernel(store), chat_service=ChatService(store, relay)))
    hdr = {"x-boltrig-tenant": T, "x-boltrig-subject": "alice", "x-boltrig-role": "engineer"}
    # the /search route is not shadowed by /{conversation_id} and is owner-scoped
    res = client.get("/v1/conversations/search?q=budget", headers=hdr)
    assert res.status_code == 200
    body = res.json()
    assert [r["id"] for r in body["results"]] == ["a0"]  # never bob's
    assert body["next_offset"] is None
    # empty query is rejected fail-closed
    assert client.get("/v1/conversations/search?q=", headers=hdr).status_code == 400
