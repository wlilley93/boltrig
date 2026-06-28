"""Conversation confidentiality (SEC-25, FR-CONV-06): owner + scoped roles only."""

import pytest

from nankle.fleet.chat import ChatService, ConversationForbidden
from nankle.kernel.events import EventRelay
from nankle.store import InMemoryStore

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
