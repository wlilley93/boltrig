"""Conversation confidentiality (SEC-25, FR-CONV-06): owner + scoped roles only."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.fleet.chat import ChatService, ConversationForbidden
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.kernel.events import EventRelay
from boltrig.models import Conversation
from boltrig.store import InMemoryStore

T = "acme"


def _stub_executor(events):
    async def executor(*, run_id, relay, **kw):
        for ev in events:
            relay.publish(run_id, ev)

    return executor


def _chat():
    return ChatService(
        InMemoryStore(), EventRelay(),
        turn_executor=_stub_executor([{"type": "text_delta", "delta": "hi"}]),
    )


async def _start(chat, user, role="engineer", message="hello"):
    conv_id = None
    async for e in chat.handle_turn(tenant_id=T, user_id=user, role=role, message=message):
        if e["type"] == "message_start":
            conv_id = e["conversation_id"]
    return conv_id


@pytest.mark.security
@pytest.mark.invariant("SEC-25")
@pytest.mark.invariant("FR-CONV-06")
async def test_other_user_cannot_read_conversation():
    chat = _chat()
    conv_id = await _start(chat, "alice")
    with pytest.raises(ConversationForbidden):  # bob, same tenant, not the owner
        await chat.get_messages(T, "bob", "engineer", conv_id)
    assert await chat.get_messages(T, "alice", "engineer", conv_id)  # owner can
    assert await chat.get_messages(T, "carol", "org-admin", conv_id)  # scoped role can


@pytest.mark.security
@pytest.mark.invariant("SEC-25")
async def test_other_user_cannot_continue_conversation():
    chat = _chat()
    conv_id = await _start(chat, "alice")
    with pytest.raises(ConversationForbidden):
        async for _ in chat.handle_turn(
            tenant_id=T, user_id="bob", role="engineer", message="sneak", conversation_id=conv_id
        ):
            pass


@pytest.mark.security
async def test_owner_only_lists_their_conversations():
    chat = _chat()
    await _start(chat, "alice")
    await _start(chat, "bob")
    assert len(await chat.list_conversations(T, "alice")) == 1
    assert len(await chat.list_conversations(T, "bob")) == 1


# --- Rename (US-CONV-08): owner-only and validated, over the HTTP route ------

def _hdr(subject: str, role: str = "engineer") -> dict:
    return {"x-boltrig-tenant": T, "x-boltrig-subject": subject, "x-boltrig-role": role,
            "x-boltrig-grants": "", "x-boltrig-departments": ""}


def _http_client(owner: str = "alice", title: str = "first draft"):
    """A TestClient over a kernel whose store holds one conversation."""
    store = InMemoryStore()
    asyncio.run(store.create_conversation(
        Conversation(id="c1", tenant_id=T, user_id=owner, title=title)
    ))
    chat = ChatService(store, EventRelay())
    return TestClient(create_app(Kernel(store), chat_service=chat, platform={}))


@pytest.mark.security
@pytest.mark.invariant("US-CONV-08")
def test_owner_can_rename_their_conversation():
    c = _http_client()
    res = c.patch("/v1/me/conversations/c1", json={"title": "renamed thread"},
                  headers=_hdr("alice"))
    assert res.status_code == 200 and res.json() == {"status": "ok", "id": "c1"}
    listed = c.get("/v1/conversations", headers=_hdr("alice")).json()["conversations"]
    assert [x["title"] for x in listed if x["id"] == "c1"] == ["renamed thread"]


@pytest.mark.security
@pytest.mark.invariant("US-CONV-08")
@pytest.mark.invariant("SEC-25")
def test_non_owner_cannot_rename_conversation():
    c = _http_client()
    res = c.patch("/v1/me/conversations/c1", json={"title": "hijack"}, headers=_hdr("bob"))
    assert res.status_code == 403
    # the title is untouched
    listed = c.get("/v1/conversations", headers=_hdr("alice")).json()["conversations"]
    assert [x["title"] for x in listed if x["id"] == "c1"] == ["first draft"]


@pytest.mark.security
@pytest.mark.invariant("US-CONV-08")
@pytest.mark.invariant("SEC-25")
def test_org_admin_cannot_rename_another_users_conversation():
    # scoped roles may READ (SEC-25); rename stays owner-only
    c = _http_client()
    res = c.patch("/v1/me/conversations/c1", json={"title": "admin edit"},
                  headers=_hdr("carol", role="org-admin"))
    assert res.status_code == 403


@pytest.mark.security
@pytest.mark.invariant("US-CONV-08")
def test_rename_rejects_empty_title():
    c = _http_client()
    res = c.patch("/v1/me/conversations/c1", json={"title": "   "}, headers=_hdr("alice"))
    assert res.status_code == 400


@pytest.mark.security
@pytest.mark.invariant("US-CONV-08")
def test_rename_rejects_overlong_title():
    c = _http_client()
    res = c.patch("/v1/me/conversations/c1", json={"title": "x" * 121}, headers=_hdr("alice"))
    assert res.status_code == 400
