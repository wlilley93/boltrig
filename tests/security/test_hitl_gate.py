"""High-consequence / blocking verbs pause for approval and resume (SEC-14, US-HIL-01).

Also pins the approval-bypass defences (the SEC-14 sweep): an approval is bound to
the verb it gates, is single-use (no replay), and is a human decision that the
requester cannot self-approve.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.kernel.app import create_app
from boltrig.models import HITLType, PendingHuman
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
    # An approval authorises exactly one execution; a replay with the same id pauses.
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
    with pytest.raises(PendingHuman):  # replay refused -> a fresh approval is needed
        await gated_kernel.invoke(
            "ticket", "ticket.create", {"title": "x"}, make_ctx(["ticket.create"]),
            approval_id=req_id,
        )


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
async def test_approval_is_verb_bound_and_single_use():
    # An approval raised for one verb cannot authorise another, and is spent once.
    k, _ = await _build_kernel(blocking_verbs={"ticket.create"})
    req = await k.hitl.create(
        tenant_id=TENANT, run_id="r", type=HITLType.APPROVAL, question="q",
        verb="ticket.create", requested_by="agent:x",
    )
    await k.hitl.answer(TENANT, req.id, "approve", "human@acme")
    assert await k.hitl.consume_if_approved(TENANT, req.id, "payment.transfer") is False
    assert await k.hitl.consume_if_approved(TENANT, req.id, "ticket.create") is True
    assert await k.hitl.consume_if_approved(TENANT, req.id, "ticket.create") is False  # spent


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
