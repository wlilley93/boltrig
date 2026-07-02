"""Regenerate: append-plus-supersede ([2026] VJS-COUNTY 4).

Regenerate re-runs the last user message on a new run id through the ordinary
executor path, APPENDS a fresh assistant reply, and sets a marker-only
``superseded_by`` on the prior reply. These tests pin: the prior reply is frozen,
the continuity composer excludes superseded messages and stays prefix-stable, the
route is owner-only fail-closed and bounded to the last assistant message, and the
marker write emits a keys-only audit event.
"""

import pytest
from fastapi.testclient import TestClient

from boltrig.fleet.chat import ChatService, RegenerateNotEligible
from boltrig.fleet.continuity import compose_turn_task, render_transcript
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.kernel.events import EventRelay
from boltrig.models import ConversationMessage, MessageRole
from boltrig.store import InMemoryStore

T = "acme"


def _stub_executor(reply: str):
    async def executor(*, run_id, relay, **kw):
        relay.publish(run_id, {"type": "text_delta", "delta": reply})

    return executor


def _hdr(subject: str, role: str = "engineer") -> dict:
    return {"x-boltrig-tenant": T, "x-boltrig-subject": subject, "x-boltrig-role": role,
            "x-boltrig-grants": "", "x-boltrig-departments": ""}


async def _seed_turn(store, relay, reply="first answer", user="alice"):
    """Drive one real turn so the store holds [user, assistant]."""
    chat = ChatService(store, relay, turn_executor=_stub_executor(reply))
    async for _ in chat.handle_turn(tenant_id=T, user_id=user, role="engineer",
                                    message="the question"):
        pass
    conv = (await store.list_conversations(T, user))[0]
    msgs = await store.list_messages(T, conv.id)
    return conv, msgs


# --- SEC-81: append-plus-supersede, frozen prior reply ----------------------

@pytest.mark.security
@pytest.mark.invariant("SEC-81")
async def test_regenerate_appends_new_reply_and_freezes_the_old():
    store, relay = InMemoryStore(), EventRelay()
    conv, msgs = await _seed_turn(store, relay, reply="first answer")
    old = msgs[1]
    old_run, old_created, old_content = old.run_id, old.created_at, old.content

    chat = ChatService(store, relay, turn_executor=_stub_executor("second answer"))
    new_msg, superseded_id = await chat.regenerate_turn(
        tenant_id=T, user_id="alice", role="engineer",
        conversation_id=conv.id, target_message_id=old.id,
    )
    await store.mark_message_superseded(T, superseded_id, new_msg.id)

    after = await store.list_messages(T, conv.id)
    # a NEW assistant message was APPENDED on a NEW run id (insert-only, no fork)
    assert [m.role.value for m in after] == ["user", "assistant", "assistant"]
    assert new_msg.run_id != old_run and new_msg.content == "second answer"
    # the prior reply is frozen: only superseded_by changed, everything else intact
    frozen = next(m for m in after if m.id == old.id)
    assert frozen.superseded_by == new_msg.id
    assert frozen.content == old_content == "first answer"
    assert frozen.run_id == old_run and frozen.created_at == old_created


@pytest.mark.security
@pytest.mark.invariant("SEC-81")
async def test_marker_write_sets_only_superseded_by():
    store = InMemoryStore()
    msg = ConversationMessage(
        id="m1", conversation_id="c1", tenant_id=T, role=MessageRole.ASSISTANT,
        content="frozen", run_id="r1", events=[{"type": "text_delta", "delta": "frozen"}],
    )
    await store.add_message(msg)
    before = (await store.list_messages(T, "c1"))[0]
    snap = (before.content, before.run_id, tuple(map(tuple, (e.items() for e in before.events))),
            before.created_at)
    await store.mark_message_superseded(T, "m1", "m2")
    after = (await store.list_messages(T, "c1"))[0]
    assert after.superseded_by == "m2"
    # content / run_id / events / created_at are immutable under the marker write
    assert after.content == "frozen" and after.run_id == "r1"
    assert after.events == [{"type": "text_delta", "delta": "frozen"}]
    assert (after.content, after.run_id,
            tuple(map(tuple, (e.items() for e in after.events))), after.created_at) == snap


# --- SEC-82: continuity excludes superseded, prefix-stable ------------------

@pytest.mark.security
@pytest.mark.invariant("SEC-82")
def test_continuity_excludes_superseded_and_is_prefix_stable():
    def m(mid, role, content, superseded_by=None):
        return ConversationMessage(id=mid, conversation_id="c1", tenant_id=T,
                                   role=role, content=content, superseded_by=superseded_by)

    u1 = m("u1", MessageRole.USER, "ask one")
    a_old = m("a_old", MessageRole.ASSISTANT, "SUPERSEDED REPLY", superseded_by="a_new")
    a_new = m("a_new", MessageRole.ASSISTANT, "live reply")
    full = [u1, a_old, a_new]

    task = compose_turn_task(full, "ask one")
    # the superseded reply is never composed into the prompt (not presented as live)
    assert "SUPERSEDED REPLY" not in task
    assert "ask one" in task and "live reply" in task
    # prefix stability over the surviving (non-superseded) set: an earlier render is
    # a prefix of a later one - the gateway-cache guarantee (SEC-46) still holds.
    live_before = render_transcript([u1])
    live_after = render_transcript([u1, a_new])
    assert live_after.startswith(live_before)
    assert compose_turn_task(full, "ask one") == render_transcript([u1, a_new])


# --- SEC-83: owner-only, last-message-only, keys-only audit -----------------

def _client_with_seeded_turn(owner="alice", reply="first answer"):
    store, relay = InMemoryStore(), EventRelay()
    import asyncio
    conv, msgs = asyncio.run(
        _seed_turn(store, relay, reply=reply, user=owner)
    )
    chat = ChatService(store, relay, turn_executor=_stub_executor("regenerated"))
    kernel = Kernel(store)
    client = TestClient(create_app(kernel, chat_service=chat, platform={}))
    return client, kernel, store, conv, msgs


@pytest.mark.security
@pytest.mark.invariant("SEC-83")
@pytest.mark.invariant("SEC-25")
def test_regenerate_is_owner_only_fail_closed():
    client, kernel, store, conv, msgs = _client_with_seeded_turn()
    last_assistant = msgs[1].id
    url = f"/v1/me/conversations/{conv.id}/messages/{last_assistant}/regenerate"
    # a non-owner is refused 403 with NO write
    res = client.post(url, headers=_hdr("bob"))
    assert res.status_code == 403
    # a scoped read role (org-admin may READ, SEC-25) still cannot regenerate
    res = client.post(url, headers=_hdr("carol", role="org-admin"))
    assert res.status_code == 403
    import asyncio
    after = asyncio.run(store.list_messages(T, conv.id))
    assert len(after) == 2  # nothing appended, nothing superseded
    assert all(mm.superseded_by is None for mm in after)


@pytest.mark.security
@pytest.mark.invariant("SEC-83")
def test_regenerate_rejects_earlier_message():
    client, kernel, store, conv, msgs = _client_with_seeded_turn()
    earlier_user = msgs[0].id  # the user message is not the last assistant reply
    res = client.post(
        f"/v1/me/conversations/{conv.id}/messages/{earlier_user}/regenerate",
        headers=_hdr("alice"),
    )
    assert res.status_code == 409 and res.json()["reason"] == "regenerate_not_eligible"
    import asyncio
    after = asyncio.run(store.list_messages(T, conv.id))
    assert len(after) == 2 and all(mm.superseded_by is None for mm in after)
    # the service-level guard raises before any re-run / persist
    chat = ChatService(store, EventRelay(), turn_executor=_stub_executor("x"))
    with pytest.raises(RegenerateNotEligible):
        asyncio.run(chat.regenerate_turn(
            tenant_id=T, user_id="alice", role="engineer",
            conversation_id=conv.id, target_message_id=earlier_user,
        ))


@pytest.mark.security
@pytest.mark.invariant("SEC-83")
def test_supersede_emits_keys_only_audit_event():
    client, kernel, store, conv, msgs = _client_with_seeded_turn(reply="first answer")
    last_assistant = msgs[1].id
    res = client.post(
        f"/v1/me/conversations/{conv.id}/messages/{last_assistant}/regenerate",
        headers=_hdr("alice"),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["superseded"] == last_assistant and body["message_id"] != last_assistant

    import asyncio
    events = asyncio.run(store.audit_query(T, limit=200))
    supersede = [e for e in events if e.verb == "data.conversation.message.supersede"]
    assert len(supersede) == 1
    detail = supersede[0].detail
    assert detail["superseded"] == last_assistant
    assert detail["superseded_by"] == body["message_id"]
    # keys only: no message content anywhere in the audit detail
    assert "first answer" not in str(detail) and "regenerated" not in str(detail)
