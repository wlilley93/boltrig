"""Chat attachments ([2026] VJS-COUNTY 3): inline, size-capped attachment records
on the message row, enforced fail-closed at intake and reaching the model only as
typed untrusted data.

The court held for inline JSONB attachments carried through the existing message
contract - no object store, no storage credential. These tests pin the load-bearing
guarantees: caps are enforced on DECODED bytes and count before anything persists, a
manifest can only tighten a cap, text attachments are enveloped and non-text ones are
never decoded into the task.
"""

import base64
import types

import pytest

from boltrig.config.manifest import (
    DEFAULT_MAX_ATTACHMENTS,
    DEFAULT_MAX_ATTACHMENT_BYTES,
    DEFAULT_MAX_TOTAL_ATTACHMENT_BYTES,
    ChatConfig,
    _parse_chat,
)
from boltrig.fleet.chat import (
    AttachmentRejected,
    ChatService,
    attachment_task_supplement,
    build_turn_executor,
)
from boltrig.kernel.events import EventRelay
from boltrig.models import GrantSet, TenantPermissions
from boltrig.store import InMemoryStore

T = "acme"


def _att(name: str, media_type: str, raw: bytes | str) -> dict:
    body = raw.encode() if isinstance(raw, str) else raw
    return {"name": name, "media_type": media_type,
            "data": base64.b64encode(body).decode()}


def _stub_executor(events):
    async def executor(*, run_id, relay, **kw):
        for ev in events:
            relay.publish(run_id, ev)

    return executor


async def _run(chat, **kw):
    async for _ in chat.handle_turn(tenant_id=T, user_id="alice", role="engineer", **kw):
        pass


# --- D3: fail-closed cap enforcement, nothing persisted ---------------------

@pytest.mark.security
@pytest.mark.invariant("SEC-79")
async def test_over_cap_turn_is_rejected_with_nothing_persisted():
    store, relay = InMemoryStore(), EventRelay()
    chat = ChatService(
        store, relay, turn_executor=_stub_executor([{"type": "text_delta", "delta": "hi"}]),
        chat_config=ChatConfig(max_attachments=2),
    )
    over = [_att(f"f{i}.txt", "text/plain", "x") for i in range(3)]  # 3 > cap of 2
    with pytest.raises(AttachmentRejected):
        await _run(chat, message="hi", attachments=over)
    # nothing persisted: the turn is refused before the conversation is even created
    assert await store.list_conversations(T, "alice") == []


@pytest.mark.security
@pytest.mark.invariant("SEC-79")
async def test_per_attachment_and_total_byte_caps_enforced_on_decoded_bytes():
    store, relay = InMemoryStore(), EventRelay()
    chat = ChatService(
        store, relay, turn_executor=_stub_executor([{"type": "text_delta", "delta": "hi"}]),
        chat_config=ChatConfig(max_attachment_bytes=10, max_total_attachment_bytes=15),
    )
    # per-attachment cap: 11 decoded bytes > 10, even though base64 is longer
    with pytest.raises(AttachmentRejected):
        await _run(chat, message="hi", attachments=[_att("big.txt", "text/plain", "01234567890")])
    assert await store.list_conversations(T, "alice") == []
    # total cap: two 8-byte attachments = 16 decoded > 15, each under the per-cap
    with pytest.raises(AttachmentRejected):
        await _run(chat, message="hi", attachments=[
            _att("a.txt", "text/plain", "01234567"),
            _att("b.txt", "text/plain", "01234567"),
        ])
    assert await store.list_conversations(T, "alice") == []
    # within both caps: one 8-byte attachment persists on the user message row
    await _run(chat, message="hi", attachments=[_att("ok.txt", "text/plain", "01234567")])
    conv = (await store.list_conversations(T, "alice"))[0]
    msgs = await store.list_messages(T, conv.id)
    assert msgs[0].role.value == "user"
    assert [a["size"] for a in msgs[0].attachments] == [8]


@pytest.mark.security
@pytest.mark.invariant("SEC-79")
def test_manifest_can_only_tighten_caps_never_loosen():
    # a manifest that tries to LOOSEN every cap above the code default is clamped to
    # the default (min(default, manifest)); a tightening manifest wins.
    loosen = _parse_chat({"attachments": {
        "max_count": DEFAULT_MAX_ATTACHMENTS + 100,
        "max_bytes": DEFAULT_MAX_ATTACHMENT_BYTES * 10,
        "max_total_bytes": DEFAULT_MAX_TOTAL_ATTACHMENT_BYTES * 10,
    }})
    assert loosen.max_attachments == DEFAULT_MAX_ATTACHMENTS
    assert loosen.max_attachment_bytes == DEFAULT_MAX_ATTACHMENT_BYTES
    assert loosen.max_total_attachment_bytes == DEFAULT_MAX_TOTAL_ATTACHMENT_BYTES
    tighten = _parse_chat({"attachments": {"max_count": 1, "max_bytes": 64}})
    assert tighten.max_attachments == 1
    assert tighten.max_attachment_bytes == 64
    # unspecified caps keep the code default
    assert tighten.max_total_attachment_bytes == DEFAULT_MAX_TOTAL_ATTACHMENT_BYTES


# --- D4: content reaches the model only as data -----------------------------

def _executor_capturing_task(store):
    captured: list[str] = []

    async def spawn(tenant_id, task, skills, prefer, context, *,
                    partial_on_budget=True, grant_ceiling=None):
        captured.append(task)
        return {"summary": "ok"}

    spawner = types.SimpleNamespace(spawn=spawn)
    kernel = types.SimpleNamespace(store=store)
    return build_turn_executor(kernel, spawner, continuity=True), captured


@pytest.mark.security
@pytest.mark.invariant("SEC-80")
async def test_text_attachment_is_enveloped_into_the_task():
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    executor, captured = _executor_capturing_task(store)
    chat = ChatService(store, EventRelay(), turn_executor=executor)
    await _run(chat, message="summarise this", attachments=[
        _att("notes.txt", "text/plain", "the secret plan is in the log"),
    ])
    task = captured[-1]
    # the text attachment body reaches the task ONLY inside a typed untrusted envelope
    assert '<untrusted kind="attachment"' in task
    assert "the secret plan is in the log" in task
    # helper unit: text -> envelope
    supp = attachment_task_supplement([_att("a.txt", "text/plain", "hello world")])
    assert '<untrusted kind="attachment"' in supp and "hello world" in supp


@pytest.mark.security
@pytest.mark.invariant("SEC-80")
async def test_non_text_attachment_never_enters_the_task():
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    executor, captured = _executor_capturing_task(store)
    chat = ChatService(store, EventRelay(), turn_executor=executor)
    marker = b"\x89PNG\r\n binary-marker-not-for-the-model"
    await _run(chat, message="look at this image", attachments=[
        {"name": "shot.png", "media_type": "image/png",
         "data": base64.b64encode(marker).decode()},
    ])
    task = captured[-1]
    # the non-text attachment is persisted record-only but never decoded into the task
    assert "binary-marker-not-for-the-model" not in task
    assert base64.b64encode(marker).decode() not in task
    assert "shot.png" not in task
    # it IS persisted on the message row (record-only)
    conv = (await store.list_conversations(T, "alice"))[0]
    msgs = await store.list_messages(T, conv.id)
    assert [a["media_type"] for a in msgs[0].attachments] == ["image/png"]
    # helper unit: non-text -> empty supplement
    assert attachment_task_supplement([
        {"name": "x.png", "media_type": "image/png", "data": base64.b64encode(marker).decode()}
    ]) == ""
