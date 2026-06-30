"""Audit is append-only, hash-chained, and tamper-evident (SEC-16, K-19)."""

import pytest

from tests.conftest import TENANT, make_ctx


@pytest.mark.kernel
@pytest.mark.invariant("SEC-16")
async def test_every_action_is_audited(kernel):
    await kernel.invoke(
        "ticket", "ticket.create", {"title": "x"}, make_ctx(["ticket.create"])
    )
    events = await kernel.store.audit_query(TENANT)
    assert len(events) == 1
    assert events[0].verb == "ticket.create"
    assert events[0].status == "ok"
    assert events[0].seq == 1 and events[0].prev_hash is None and events[0].hash


@pytest.mark.kernel
@pytest.mark.invariant("SEC-16")
async def test_denied_actions_are_also_audited(kernel):
    from boltrig.models import GrantMissing

    with pytest.raises(GrantMissing):
        await kernel.invoke("ticket", "ticket.create", {"title": "x"}, make_ctx([]))
    events = await kernel.store.audit_query(TENANT)
    assert events[-1].status == "grant_missing"


@pytest.mark.kernel
@pytest.mark.invariant("K-19")
async def test_chain_verifies_and_detects_tampering(kernel):
    for i in range(3):
        await kernel.invoke(
            "ticket", "ticket.create", {"title": f"t{i}"}, make_ctx(["ticket.create"])
        )
    ok, bad = await kernel.audit.verify(TENANT)
    assert ok and bad is None

    # tamper with a row in the middle of the chain
    events = await kernel.store.audit_query(TENANT)
    events[1].status = "tampered"
    ok2, bad2 = await kernel.audit.verify(TENANT)
    assert not ok2 and bad2 == events[1].seq
