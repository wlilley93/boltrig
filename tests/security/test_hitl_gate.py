"""High-consequence / blocking verbs pause for approval and resume (SEC-14, US-HIL-01).

Also pins the approval-bypass defences (the SEC-14 sweep): an approval is bound to
the verb it gates, is single-use (no replay), and is a human decision that the
requester cannot self-approve.
"""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from boltrig.kernel.app import create_app
from boltrig.kernel.hitl import approval_request_fingerprint
from boltrig.kernel.ratelimit import RateLimiter
from boltrig.models import (
    ApprovalNotHoldable,
    HITLRequest,
    HITLStateConflict,
    HITLStatus,
    HITLType,
    PendingHuman,
    RateLimit,
    RateLimited,
    TargetType,
    Urgency,
    VerbBinding,
)
from tests.conftest import TENANT, _build_kernel, make_ctx


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
async def test_blocking_verb_pauses_for_approval(gated_kernel):
    with pytest.raises(PendingHuman) as exc:
        await gated_kernel.invoke(
            "ticket", "ticket.create", {"title": "x"}, make_ctx(["ticket.create"])
        )
    # a pending request now exists
    pending = await gated_kernel.hitl.list_pending(TENANT)
    assert any(r.id == exc.value.hitl_request_id for r in pending)


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
async def test_approval_records_literal_inputs_without_storing_secrets(gated_kernel):
    ctx = make_ctx(
        ["ticket.create"], actor="alice", actor_tier="human", on_behalf_of="owner"
    )
    with pytest.raises(PendingHuman) as exc:
        await gated_kernel.invoke(
            "ticket",
            "ticket.create",
            {
                "title": "ship the release",
                "metadata": {"region": "eu-west", "api_key": "sk-not-stored"},
            },
            ctx,
        )

    request = await gated_kernel.hitl.get(TENANT, exc.value.hitl_request_id)
    assert request is not None
    display = json.loads(request.context)
    assert display == {
        "inputs": {
            "metadata": {"api_key": "[redacted]", "region": "eu-west"},
            "title": "ship the release",
        },
        "requested_by": "alice",
        "requested_on_behalf_of": "owner",
        "verb": "ticket.create",
        "version": 1,
    }
    assert "sk-not-stored" not in request.context


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
async def test_resumes_after_approval(gated_kernel):
    with pytest.raises(PendingHuman) as exc:
        await gated_kernel.invoke(
            "ticket", "ticket.create", {"title": "x"}, make_ctx(["ticket.create"])
        )
    req_id = exc.value.hitl_request_id
    await gated_kernel.hitl.answer(TENANT, req_id, "approve", "lead@acme")
    out = await gated_kernel.invoke(
        "ticket", "ticket.create", {"title": "x"}, make_ctx(["ticket.create"]),
        approval_id=req_id,
    )
    assert out["status"] == "open"


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
async def test_approval_is_single_use(gated_kernel):
    # An approval authorises exactly one execution. A replay with the spent id
    # FAILS LOUDLY (409 hitl_state_conflict) rather than silently re-pending:
    # the spend already ran its invocation (succeeded or failed - e.g. the
    # HITL-resume lane consumed it), so a fresh 202 here would loop forever,
    # with the caller unable to tell "spent" from "still waiting".
    with pytest.raises(PendingHuman) as exc:
        await gated_kernel.invoke(
            "ticket", "ticket.create", {"title": "x"}, make_ctx(["ticket.create"])
        )
    req_id = exc.value.hitl_request_id
    await gated_kernel.hitl.answer(TENANT, req_id, "approve", "lead@acme")
    out = await gated_kernel.invoke(
        "ticket", "ticket.create", {"title": "x"}, make_ctx(["ticket.create"]),
        approval_id=req_id,
    )
    assert out["status"] == "open"
    with pytest.raises(HITLStateConflict):  # spent approval: loud, never a re-pend
        await gated_kernel.invoke(
            "ticket", "ticket.create", {"title": "x"}, make_ctx(["ticket.create"]),
            approval_id=req_id,
        )
    assert await gated_kernel.hitl.list_pending(TENANT) == []


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
async def test_rate_limited_gated_call_does_not_spend_the_approval():
    # The throttle is a PRE-EXECUTION kernel refusal: the adapter provably never
    # ran, so the human approval must survive it and stay usable on the retry that
    # RateLimited's retry_after invites. Spending it first left the caller holding
    # a CONSUMED approval and a 409 claiming "its invocation already ran" about a
    # high-consequence action that never happened.
    k, _ = await _build_kernel(blocking_verbs={"ticket.create"})
    await k.store.upsert_binding(
        VerbBinding(
            verb_id="ticket.create",
            tenant_id=TENANT,
            target_type=TargetType.ADAPTER,
            target_ref="memory-tickets",
            rate_limit=RateLimit(per="minute", max=1, scope="tenant"),
        )
    )

    async def approved(title: str) -> str:
        with pytest.raises(PendingHuman) as pend:
            await k.invoke(
                "ticket", "ticket.create", {"title": title}, make_ctx(["ticket.create"])
            )
        req_id = pend.value.hitl_request_id
        await k.hitl.answer(TENANT, req_id, "approve", "lead@acme")
        return req_id

    first = await approved("one")
    await k.invoke(
        "ticket", "ticket.create", {"title": "one"}, make_ctx(["ticket.create"]),
        approval_id=first,
    )  # burns the window's only token

    second = await approved("two")
    with pytest.raises(RateLimited):
        await k.invoke(
            "ticket", "ticket.create", {"title": "two"}, make_ctx(["ticket.create"]),
            approval_id=second,
        )
    held = await k.hitl.get(TENANT, second)
    assert held is not None
    assert held.status == HITLStatus.ANSWERED, (
        "the rate-limit gate spent the human approval for a call that never "
        "executed; the retry is now met with 'its invocation already ran'"
    )

    k.dispatcher._rate = RateLimiter()  # the rate window has passed
    out = await k.invoke(
        "ticket", "ticket.create", {"title": "two"}, make_ctx(["ticket.create"]),
        approval_id=second,
    )
    assert out["status"] == "open"


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
async def test_approval_is_verb_bound_and_single_use():
    # An approval raised for one verb cannot authorise another, and is spent once.
    k, _ = await _build_kernel(blocking_verbs={"ticket.create"})
    req = await k.hitl.create(
        tenant_id=TENANT, run_id="r", type=HITLType.APPROVAL, question="q",
        verb="ticket.create", requested_by="agent:x", request_fingerprint="create-fp",
    )
    await k.hitl.answer(TENANT, req.id, "approve", "human@acme")
    assert await k.hitl.consume_if_approved(
        TENANT, req.id, "payment.transfer", "create-fp"
    ) is False
    assert await k.hitl.consume_if_approved(
        TENANT, req.id, "ticket.create", "wrong-fp"
    ) is False
    assert await k.hitl.consume_if_approved(
        TENANT, req.id, "ticket.create", "create-fp"
    ) is True
    assert await k.hitl.consume_if_approved(
        TENANT, req.id, "ticket.create", "create-fp"
    ) is False  # spent


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
async def test_consumed_approval_cannot_be_re_answered():
    # Regression: answering a consumed request used to move it back to ANSWERED,
    # letting the same approval clear the gate a second time.
    k, _ = await _build_kernel(blocking_verbs={"ticket.create"})
    req = await k.hitl.create(
        tenant_id=TENANT, run_id="r", type=HITLType.APPROVAL, question="q",
        verb="ticket.create", requested_by="agent:x", request_fingerprint="create-fp",
    )
    await k.hitl.answer(TENANT, req.id, "approve", "human@acme")
    assert await k.hitl.consume_if_approved(
        TENANT, req.id, "ticket.create", "create-fp"
    ) is True

    with pytest.raises(HITLStateConflict):
        await k.hitl.answer(TENANT, req.id, "approve", "human2@acme")
    assert await k.hitl.consume_if_approved(
        TENANT, req.id, "ticket.create", "create-fp"
    ) is False


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
async def test_escalation_answer_cannot_clear_high_consequence_gate():
    # H1: a null-verb, non-APPROVAL request (the fleet raises escalations /
    # clarifications this way) answered "approve" must NOT clear a gated verb.
    # Only a genuine, verb-bound APPROVAL may authorise. A normal APPROVAL still
    # clears its verb and is single-use.
    k, _ = await _build_kernel(blocking_verbs={"ticket.create"})
    esc = await k.hitl.create(
        tenant_id=TENANT, run_id="r", type=HITLType.ESCALATION, question="help?",
        verb=None, requested_by="agent:x",
    )
    await k.hitl.answer(TENANT, esc.id, "approve", "agent:x")
    # laundering the escalation id into the gate fails closed (type + null verb)
    assert await k.hitl.consume_if_approved(
        TENANT, esc.id, "ticket.create", "irrelevant"
    ) is False
    # a genuine APPROVAL for the verb still clears it, exactly once
    appr = await k.hitl.create(
        tenant_id=TENANT, run_id="r", type=HITLType.APPROVAL, question="q",
        verb="ticket.create", requested_by="agent:x", request_fingerprint="create-fp",
    )
    await k.hitl.answer(TENANT, appr.id, "approve", "human@acme")
    assert await k.hitl.consume_if_approved(
        TENANT, appr.id, "ticket.create", "create-fp"
    ) is True
    assert await k.hitl.consume_if_approved(
        TENANT, appr.id, "ticket.create", "create-fp"
    ) is False


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
def test_respond_rejects_agent_and_self_approval():
    # The respond route: an agent cannot answer an approval, and the requester
    # cannot approve their own request; a different human can.
    k, _ = asyncio.run(_build_kernel(blocking_verbs={"ticket.create"}))
    req = asyncio.run(
        k.hitl.create(
            tenant_id=TENANT, run_id="r", type=HITLType.APPROVAL,
            question="Approve ticket.create ?", verb="ticket.create", requested_by="agent:x",
            request_fingerprint="create-fp",
        )
    )
    c = TestClient(create_app(k, platform={}))

    def _post(subject, tier):
        return c.post(
            f"/v1/hitl/{req.id}/respond", json={"decision": "approve"},
            headers={"x-boltrig-tenant": TENANT, "x-boltrig-subject": subject,
                     "x-boltrig-tier": tier, "x-boltrig-grants": "*"},
        )

    assert _post("agent:x", "ephemeral").status_code == 403  # agent cannot approve
    assert _post("agent:x", "human").status_code == 403  # self-approval blocked
    assert _post("alice", "human").status_code == 200  # a different human can
    assert _post("bob", "human").status_code == 409  # already answered, never reusable


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
def test_respond_requires_verb_authority_assignee_and_delegation_separation():
    k, _ = asyncio.run(_build_kernel(blocking_verbs={"ticket.create"}))
    c = TestClient(create_app(k, platform={}))

    def _request(**kwargs):
        return asyncio.run(
            k.hitl.create(
                tenant_id=TENANT,
                run_id="r",
                type=HITLType.APPROVAL,
                question="Approve ticket.create ?",
                verb="ticket.create",
                requested_by="requesting-agent",
                request_fingerprint="create-fp",
                **kwargs,
            )
        )

    def _post(req_id, subject, grants="ticket.create", obo=None):
        headers = {
            "x-boltrig-tenant": TENANT,
            "x-boltrig-subject": subject,
            "x-boltrig-tier": "human",
            "x-boltrig-role": "agent",
            "x-boltrig-grants": grants,
        }
        if obo:
            headers["x-boltrig-obo"] = obo
        return c.post(
            f"/v1/hitl/{req_id}/respond",
            json={"decision": "approve"},
            headers=headers,
        )

    authority = _request()
    assert _post(authority.id, "viewer", grants="ticket.read").status_code == 403
    assert asyncio.run(k.hitl.get(TENANT, authority.id)).status == HITLStatus.PENDING
    assert _post(authority.id, "security-admin").status_code == 200

    assigned = _request(assignee="alice")
    assert _post(assigned.id, "bob").status_code == 403
    assert _post(assigned.id, "alice").status_code == 200

    delegated = _request(requested_on_behalf_of="owner")
    assert _post(delegated.id, "owner").status_code == 403
    assert _post(delegated.id, "delegate", obo="owner").status_code == 403
    assert _post(delegated.id, "independent-reviewer").status_code == 200


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
def test_legacy_unbound_approval_fails_closed():
    k, _ = asyncio.run(_build_kernel(blocking_verbs={"ticket.create"}))
    legacy = HITLRequest(
        id="legacy-unbound",
        tenant_id=TENANT,
        run_id="r",
        type=HITLType.APPROVAL,
        urgency=Urgency.BLOCKING,
        context="legacy",
        question="Approve?",
        verb="ticket.create",
        requested_by="requesting-agent",
    )
    asyncio.run(k.store.create_hitl_request(legacy))
    client = TestClient(create_app(k, platform={}))
    response = client.post(
        f"/v1/hitl/{legacy.id}/respond",
        json={"decision": "approve"},
        headers={
            "x-boltrig-tenant": TENANT,
            "x-boltrig-subject": "security-admin",
            "x-boltrig-tier": "human",
            "x-boltrig-grants": "ticket.create",
        },
    )
    assert response.status_code == 409
    assert asyncio.run(k.hitl.get(TENANT, legacy.id)).status == HITLStatus.PENDING


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
async def test_approval_is_bound_to_params_and_initiating_principal():
    k, _ = await _build_kernel(blocking_verbs={"ticket.create"})
    alice = make_ctx(
        ["ticket.create"], actor="alice", actor_tier="human", on_behalf_of="owner"
    )
    with pytest.raises(PendingHuman) as exc:
        await k.invoke("ticket", "ticket.create", {"title": "original"}, alice)
    request_id = exc.value.hitl_request_id
    await k.hitl.answer(TENANT, request_id, "approve", "security-admin")

    # A changed payload cannot spend Alice's approval.
    with pytest.raises(PendingHuman):
        await k.invoke(
            "ticket", "ticket.create", {"title": "changed"}, alice,
            approval_id=request_id,
        )
    assert (await k.hitl.get(TENANT, request_id)).status == HITLStatus.ANSWERED

    # Nor can a different caller (even with the same verb grant) spend it.
    mallory = make_ctx(
        ["ticket.create"], actor="mallory", actor_tier="human", on_behalf_of="owner"
    )
    with pytest.raises(PendingHuman):
        await k.invoke(
            "ticket", "ticket.create", {"title": "original"}, mallory,
            approval_id=request_id,
        )
    assert (await k.hitl.get(TENANT, request_id)).status == HITLStatus.ANSWERED

    changed_delegation = make_ctx(
        ["ticket.create"], actor="alice", actor_tier="human", on_behalf_of="other-owner"
    )
    with pytest.raises(PendingHuman):
        await k.invoke(
            "ticket", "ticket.create", {"title": "original"}, changed_delegation,
            approval_id=request_id,
        )
    assert (await k.hitl.get(TENANT, request_id)).status == HITLStatus.ANSWERED

    # The exact original request remains legitimate and consumes it once.
    out = await k.invoke(
        "ticket", "ticket.create", {"title": "original"}, alice,
        approval_id=request_id,
    )
    assert out["title"] == "original"


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
async def test_mutable_adapter_approval_context_is_recomputed():
    k, adapter = await _build_kernel(blocking_verbs={"ticket.create"})
    state = {"generation": 1}
    seen = {}
    original_execute = adapter.execute

    async def approval_context(verb, params, context):
        return dict(state)

    async def capture_execute(verb, params, credential, context):
        seen["context"] = context
        return await original_execute(verb, params, credential, context)

    adapter.approval_context = approval_context
    adapter.execute = capture_execute
    ctx = make_ctx(["ticket.create"], actor="alice", actor_tier="human")
    with pytest.raises(PendingHuman) as exc:
        await k.invoke("ticket", "ticket.create", {"title": "x"}, ctx)
    request_id = exc.value.hitl_request_id
    await k.hitl.answer(TENANT, request_id, "approve", "security-admin")

    state["generation"] = 2
    with pytest.raises(PendingHuman):
        await k.invoke(
            "ticket", "ticket.create", {"title": "x"}, ctx,
            approval_id=request_id,
        )
    assert (await k.hitl.get(TENANT, request_id)).status == HITLStatus.ANSWERED

    state["generation"] = 1
    await k.invoke(
        "ticket", "ticket.create", {"title": "x"}, ctx,
        approval_id=request_id,
    )
    invoked = seen["context"]
    assert invoked.extra["approval_resource_context"] == {"generation": 1}
    assert invoked.extra["approval_request_fingerprint"] == (
        await k.hitl.get(TENANT, request_id)
    ).request_fingerprint


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
def test_approval_fingerprint_canonicalises_json_order_and_unicode():
    ctx = make_ctx(["ticket.create"], actor="alice", actor_tier="human")
    first = approval_request_fingerprint(
        noun="ticket",
        verb="ticket.create",
        params={"nested": {"b": 2, "a": "e\u0301"}},
        context=ctx,
        resource_context={"revision": 7, "flags": [True, None]},
    )
    second = approval_request_fingerprint(
        noun="ticket",
        verb="ticket.create",
        params={"nested": {"a": "é", "b": 2}},
        context=ctx,
        resource_context={"flags": [True, None], "revision": 7},
    )
    assert first == second
    assert len(first) == 64


@pytest.mark.security
async def test_rejection_does_not_execute(gated_kernel):
    with pytest.raises(PendingHuman) as exc:
        await gated_kernel.invoke(
            "ticket", "ticket.create", {"title": "x"}, make_ctx(["ticket.create"])
        )
    req_id = exc.value.hitl_request_id
    await gated_kernel.hitl.answer(TENANT, req_id, "reject", "lead@acme")
    # a rejected approval id does not authorise the verb -> still pauses (new request)
    with pytest.raises(PendingHuman):
        await gated_kernel.invoke(
            "ticket", "ticket.create", {"title": "x"}, make_ctx(["ticket.create"]),
            approval_id=req_id,
        )


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
async def test_a_gated_verb_on_a_lane_with_no_redeemer_mints_nothing():
    """The anti-regression guard for decision 0018's subsidiary holding.

    The ground truth: a human approved ``opbox.add_comment`` inside a chat turn,
    the request reached ANSWERED and never CONSUMED, and the comment was never
    posted - an approval instrument minted on a lane with nothing able to claim
    it. The gate that mints must be able to NAME the redeemer from the record, so
    that state cannot be reached rather than being repaired once.

    This drives the SHIPPED gate through the SHIPPED chokepoint. The lane is made
    redeemer-less the only way it honestly can be - a store that cannot record the
    pause, so no held call could ever be replayed from it - and the assertion is
    on the ``hitl_requests`` rows themselves: delete the gate and this test fails,
    because the call pauses with a request nothing could redeem.
    """
    k, _ = await _build_kernel(blocking_verbs={"ticket.create"})

    class UnrecordableStore:
        """The kernel's store with the held-call seams taken away."""

        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            if name in {"upsert_checkpoint", "list_checkpoints", "set_credential_ref"}:
                raise AttributeError(name)
            return getattr(self._inner, name)

    inner = k.store
    k.dispatcher._store = UnrecordableStore(inner)

    with pytest.raises(ApprovalNotHoldable) as refused:
        await k.invoke(
            "ticket", "ticket.create", {"title": "x"},
            make_ctx(["ticket.create"], run_id="orphan-run"),
        )
    assert refused.value.verb == "ticket.create"
    assert refused.value.status_code == 409
    # nothing was created: no request to answer, so no answer to strand
    assert await k.hitl.list_pending(TENANT) == []
    assert inner._hitl == {}

    # and the guard is not simply refusing everything: the same verb on a lane
    # that CAN hold the write still pauses for a human exactly as before.
    k.dispatcher._store = inner
    with pytest.raises(PendingHuman):
        await k.invoke(
            "ticket", "ticket.create", {"title": "x"},
            make_ctx(["ticket.create"], run_id="held-run"),
        )
    assert len(await k.hitl.list_pending(TENANT)) == 1
