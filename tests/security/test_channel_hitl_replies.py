"""Channel-native HITL replies (decision 0003; SEC-14, SEC-179).

A pending approval/question already REACHES a bound surface (SEC-179); these
tests pin the way back: a BOUND sender answers from the channel itself. An
explicit ``/approve <id>`` | ``/deny <id>`` | ``/answer <id> <text>`` command -
or a plain reply in a thread with EXACTLY ONE pending item addressed to that
sender - runs through the SAME respond/answer logic and the SAME fail-closed
eligibility as the API (hitl_response_auth), as the resolved principal. An
unbound sender is rejected like any unknown sender; an ambiguous reply (zero or
several pending items) is ordinary intake, never a guess.
"""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from boltrig.adapters.builtin.inbound_webhook import (
    canonical_body,
    expected_signature,
    signed_content,
)
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    Channel,
    ChannelBinding,
    GrantSet,
    HITLStatus,
    HITLType,
    TenantPermissions,
    WorkItem,
    WorkStatus,
)
from boltrig.store import InMemoryStore

T = "acme"
SECRET = "whsec_hitl_reply"


async def _kernel_with_channel() -> tuple[Kernel, InMemoryStore]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    await store.upsert_channel(
        Channel(
            id="ch-1", tenant_id=T, platform="webhook", name="Ops", transport="webhook",
            credential_ref="cred-1", config={"sender_field": "sender"},
        )
    )
    await store.set_credential_ref(T, "cred-1", {"secret": SECRET})
    # alice is the approver/owner; bob is bound but never the approver
    await store.upsert_channel_binding(
        ChannelBinding(
            id="b-1", tenant_id=T, channel_id="ch-1", platform="webhook",
            external_user_id="U-42", subject="alice", role="member",
        )
    )
    await store.upsert_channel_binding(
        ChannelBinding(
            id="b-2", tenant_id=T, channel_id="ch-1", platform="webhook",
            external_user_id="U-7", subject="bob", role="member",
        )
    )
    return Kernel(store), store


def _client(kernel: Kernel) -> TestClient:
    return TestClient(create_app(kernel))


def _signed(payload: dict) -> dict:
    ts = int(time.time())
    sig = expected_signature(SECRET, signed_content(ts, canonical_body(payload)))
    return {"x-boltrig-signature": f"t={ts},v1={sig}"}


def _inbound(client: TestClient, sender: str, text: str, *, delivery: str,
             thread: str | None = None, channel_id: str = "ch-1"):
    payload = {"sender": sender, "type": "message", "text": text, "id": delivery}
    if thread is not None:
        payload["thread"] = thread
    return client.post(
        f"/v1/channels/{channel_id}/inbound", json=payload, headers=_signed(payload)
    )


async def _work_item(request_id: str, thread: str) -> WorkItem:
    return WorkItem(
        id=f"work-{request_id}", tenant_id=T, source="webhook",
        intent="needs a human", confidence=1.0, convergent=False,
        status=WorkStatus.AWAITING_HUMAN, hatchet_run_id=f"run-{request_id}",
        on_behalf_of="alice",
        reply_route={"channel_id": "ch-1", "thread": thread, "sender": "U-42"},
    )


async def _seed_approval(kernel: Kernel, request_id: str = "a-1", *,
                         assignee: str = "alice", thread: str | None = None):
    work_item_id = None
    if thread is not None:
        work_item_id = f"work-{request_id}"
        await kernel.store.create_work_item(await _work_item(request_id, thread))
    return await kernel.hitl.create(
        tenant_id=T, run_id=f"run-{request_id}", type=HITLType.APPROVAL,
        question="Approve ticket.create ?", verb="ticket.create",
        requested_by="agent:x", request_fingerprint=f"fp-{request_id}",
        assignee=assignee, work_item_id=work_item_id,
    )


async def _seed_question(kernel: Kernel, request_id: str = "q-1", *,
                         thread: str = "T-1"):
    await kernel.store.create_work_item(await _work_item(request_id, thread))
    return await kernel.hitl.create(
        tenant_id=T, run_id=f"run-{request_id}", type=HITLType.QUESTION,
        question="Which colour should ship?", work_item_id=f"work-{request_id}",
        requested_by="agent:x", requested_on_behalf_of="alice",
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
@pytest.mark.invariant("SEC-179")
def test_channel_approve_clears_a_pending_approval_as_the_bound_approver():
    kernel, store = asyncio.run(_kernel_with_channel())
    req = asyncio.run(_seed_approval(kernel))
    fired: list[str] = []
    kernel.hitl.set_resume_notifier(lambda r: fired.append(r.id))

    r = _inbound(_client(kernel), "U-42", f"/approve {req.id}", delivery="evt-a1")
    assert r.status_code == 200
    assert r.json()["hitl_reply"] == "approve"
    assert r.json()["request"] == req.id
    # the pending approval is cleared AS the bound approver, exactly once
    assert asyncio.run(kernel.hitl.get(T, req.id)).status == HITLStatus.ANSWERED
    resp = asyncio.run(kernel.store.get_hitl_response(T, req.id))
    assert resp is not None
    assert resp.decision == "approve" and resp.respondent == "alice"
    assert fired == [req.id]  # the answer -> resume bridge fired (NFR-REL-03)
    assert asyncio.run(store.list_work_items(T)) == []  # no work item minted
    # a replayed command can never re-answer (the API's 409, fail-closed)
    again = _inbound(_client(kernel), "U-42", f"/approve {req.id}", delivery="evt-a2")
    assert again.status_code == 409
    assert asyncio.run(kernel.hitl.get(T, req.id)).status == HITLStatus.ANSWERED


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
def test_channel_approve_and_deny_use_the_api_eligibility():
    kernel, _ = asyncio.run(_kernel_with_channel())
    client = _client(kernel)
    assigned = asyncio.run(_seed_approval(kernel, "a-1", assignee="alice"))

    # a bound sender who is NOT the approver gets the same fail-closed denial
    denied = _inbound(client, "U-7", f"/approve {assigned.id}", delivery="evt-d1")
    assert denied.status_code == 403
    assert denied.json()["status"] == "denied"
    assert asyncio.run(kernel.hitl.get(T, assigned.id)).status == HITLStatus.PENDING
    assert asyncio.run(kernel.store.get_hitl_response(T, assigned.id)) is None

    # self-approval is blocked over the channel exactly as over the API
    own = asyncio.run(
        kernel.hitl.create(
            tenant_id=T, run_id="run-a2", type=HITLType.APPROVAL,
            question="Approve ticket.create ?", verb="ticket.create",
            requested_by="agent:x", request_fingerprint="fp-a2",
            requested_on_behalf_of="alice",
        )
    )
    selfish = _inbound(client, "U-42", f"/approve {own.id}", delivery="evt-d2")
    assert selfish.status_code == 403
    assert asyncio.run(kernel.hitl.get(T, own.id)).status == HITLStatus.PENDING

    # /deny records a non-approving decision through the same path
    r = _inbound(client, "U-42", f"/deny {assigned.id}", delivery="evt-d3")
    assert r.status_code == 200
    assert r.json()["hitl_reply"] == "deny"
    resp = asyncio.run(kernel.store.get_hitl_response(T, assigned.id))
    assert resp is not None and resp.decision == "reject"
    assert asyncio.run(
        kernel.hitl.consume_if_approved(T, assigned.id, "ticket.create", "fp-a-1")
    ) is False  # a denial never authorises the gated verb


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
@pytest.mark.invariant("SEC-179")
def test_channel_answer_feeds_a_question_back_and_resumes():
    kernel, store = asyncio.run(_kernel_with_channel())
    question = asyncio.run(_seed_question(kernel))
    fired: list[str] = []
    kernel.hitl.set_resume_notifier(lambda r: fired.append(r.id))

    r = _inbound(
        _client(kernel), "U-42", f"/answer {question.id} the blue one",
        delivery="evt-q1", thread="T-1",
    )
    assert r.status_code == 200
    assert r.json()["hitl_reply"] == "answer"
    assert asyncio.run(kernel.hitl.get(T, question.id)).status == HITLStatus.ANSWERED
    stored = asyncio.run(kernel.store.get_hitl_response(T, question.id))
    assert stored is not None and stored.respondent == "alice"
    # the answer is enveloped as DATA before it is replayed into the run (SEC-72)
    assert stored.decision.startswith('<untrusted kind="user_answer"')
    assert "the blue one" in stored.decision
    assert fired == [question.id]  # the paused run is resumed
    # only the seeded work item exists - the reply minted none
    assert len(asyncio.run(store.list_work_items(T))) == 1

    # a QUESTION can never be laundered into clearing the approval gate
    other = asyncio.run(_seed_question(kernel, "q-2"))
    laundered = _inbound(_client(kernel), "U-42", f"/approve {other.id}",
                         delivery="evt-q2")
    assert laundered.status_code == 409  # "use the question answer route"
    assert asyncio.run(kernel.hitl.get(T, other.id)).status == HITLStatus.PENDING


@pytest.mark.security
@pytest.mark.invariant("SEC-179")
def test_implicit_reply_answers_the_sole_pending_question_in_thread():
    kernel, _ = asyncio.run(_kernel_with_channel())
    client = _client(kernel)
    question = asyncio.run(_seed_question(kernel, "q-1", thread="T-1"))

    # exactly one pending item addressed to alice in T-1: a plain reply answers it
    r = _inbound(client, "U-42", "the blue one", delivery="evt-i1", thread="T-1")
    assert r.status_code == 200
    assert r.json()["hitl_reply"] == "answer"
    assert r.json()["request"] == question.id
    assert asyncio.run(kernel.hitl.get(T, question.id)).status == HITLStatus.ANSWERED

    # a plain reply in a DIFFERENT thread is ordinary intake
    other = asyncio.run(_seed_question(kernel, "q-2", thread="T-2"))
    stray = _inbound(client, "U-42", "just chatting", delivery="evt-i2", thread="T-9")
    assert stray.status_code == 202
    assert asyncio.run(kernel.hitl.get(T, other.id)).status == HITLStatus.PENDING

    # a plain reply can NEVER decide an approval: explicit /approve|/deny only
    approval = asyncio.run(_seed_approval(kernel, "a-9", thread="T-2"))
    vague = _inbound(client, "U-42", "sure why not", delivery="evt-i3", thread="T-2")
    assert vague.status_code == 202
    assert asyncio.run(kernel.hitl.get(T, approval.id)).status == HITLStatus.PENDING
    assert asyncio.run(kernel.hitl.get(T, other.id)).status == HITLStatus.PENDING


@pytest.mark.security
@pytest.mark.invariant("SEC-179")
def test_implicit_reply_with_two_pending_is_normal_intake():
    kernel, store = asyncio.run(_kernel_with_channel())
    one = asyncio.run(_seed_question(kernel, "q-1", thread="T-1"))
    two = asyncio.run(_seed_question(kernel, "q-2", thread="T-1"))

    # TWO pending items addressed to alice in T-1: ambiguous -> a normal
    # message, never a guess; both stay pending and a work item is minted
    r = _inbound(_client(kernel), "U-42", "the blue one", delivery="evt-i4",
                 thread="T-1")
    assert r.status_code == 202
    assert asyncio.run(kernel.hitl.get(T, one.id)).status == HITLStatus.PENDING
    assert asyncio.run(kernel.hitl.get(T, two.id)).status == HITLStatus.PENDING
    items = asyncio.run(store.list_work_items(T))
    assert any(w.raw.get("text") == "the blue one" for w in items)


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
def test_unbound_senders_command_is_rejected_like_an_unknown_sender():
    kernel, _ = asyncio.run(_kernel_with_channel())
    req = asyncio.run(_seed_approval(kernel))
    r = _inbound(_client(kernel), "U-stranger", f"/approve {req.id}",
                 delivery="evt-u1")
    assert r.status_code == 403
    assert r.json()["reason"] == "sender not paired"
    assert asyncio.run(kernel.hitl.get(T, req.id)).status == HITLStatus.PENDING
    assert asyncio.run(kernel.store.get_hitl_response(T, req.id)) is None


@pytest.mark.security
@pytest.mark.invariant("SEC-179")
def test_channel_reply_confirms_back_on_the_originating_thread():
    async def go():
        kernel, store = await _kernel_with_channel()
        # a SOCKET-class channel: the outcome rides the durable outbox back to
        # the thread the command came from (round-trip integrity)
        await store.upsert_channel(
            Channel(id="ch-2", tenant_id=T, platform="slack", name="Ops socket",
                    transport="socket", credential_ref="cred-2",
                    config={"sender_field": "sender"})
        )
        await store.set_credential_ref(T, "cred-2", {"secret": SECRET})
        await store.upsert_channel_binding(
            ChannelBinding(id="b-3", tenant_id=T, channel_id="ch-2",
                           platform="slack", external_user_id="U-42",
                           subject="alice", role="member")
        )
        return kernel, store

    kernel, store = asyncio.run(go())
    req = asyncio.run(_seed_approval(kernel, "a-1", thread="T-1"))
    # repoint the seeded item's reply route at the socket channel
    item = asyncio.run(store.get_work_item(T, "work-a-1"))
    item.reply_route = {"channel_id": "ch-2", "thread": "T-1", "sender": "U-42"}
    asyncio.run(store.update_work_item(item))

    r = _inbound(_client(kernel), "U-42", f"/approve {req.id}", delivery="evt-s1",
                 thread="T-1", channel_id="ch-2")
    assert r.status_code == 200
    (msg,) = asyncio.run(store.claim_channel_outbox(T, ["ch-2"], "test", 60, 20))
    assert msg.payload["event"] == "hitl_reply"
    assert msg.payload["subject"] == "alice"
    assert msg.payload["target"] == "T-1"  # the originating thread
    assert "approve" in msg.payload["text"]
