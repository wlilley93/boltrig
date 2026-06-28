"""High-consequence / blocking verbs pause for approval and resume (SEC-14, US-HIL-01)."""

import pytest

from nankle.models import PendingHuman
from tests.conftest import TENANT, make_ctx


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
