"""HITL timeout enforcement (SEC-14).

A HITL request's ``timeout_at`` is recorded AND enforced, in two layers:

- WIRED: the approval gate stamps every request it raises with the manifest's
  ``hitl.approval_timeout_seconds`` (threaded manifest -> Kernel -> HITLManager
  at construction), so a gate-created approval carries a deadline.
- LAZY: an overdue request refuses an answer with a typed 409 and transitions
  to TIMED_OUT; a stale (answered but unconsumed) approval past its deadline
  can never authorise an execution - the gate re-pends for a fresh decision.
- SWEEP: the ``boltrig.kernel.hitl_expiry`` janitor expires only overdue
  pending requests (fresh ones are untouched) and settles the linked
  AWAITING_HUMAN work item at the neutral terminal CANCELLED - never a silent
  success, never an automatic re-queue loop.
"""

import asyncio
import logging
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from boltrig.kernel.app import create_app
from boltrig.kernel.hitl_expiry import (
    DEFAULT_INTERVAL_SECONDS,
    INTERVAL_ENV,
    hitl_expiry_interval_from_env,
    run_hitl_expiry_forever,
    run_hitl_expiry_sweep,
)
from boltrig.models import (
    HITLStatus,
    HITLType,
    Organisation,
    PendingHuman,
    WorkItem,
    WorkStatus,
    utcnow,
)
from tests.conftest import TENANT, _build_kernel, make_ctx


async def _raise_approval(kernel, timeout_seconds=None):
    """Drive a gated verb to its pause and return the gate-created request."""
    with pytest.raises(PendingHuman) as exc:
        await kernel.invoke(
            "ticket", "ticket.create", {"title": "x"}, make_ctx(["ticket.create"])
        )
    request = await kernel.hitl.get(TENANT, exc.value.hitl_request_id)
    assert request is not None
    if timeout_seconds is not None:  # force the deadline (the clock is real)
        request.timeout_at = utcnow() + timedelta(seconds=timeout_seconds)
    return request


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
async def test_gate_created_approval_carries_manifest_timeout():
    # The manifest's approval_timeout_seconds travels Kernel -> HITLManager ->
    # gate: a gate-raised approval is created WITH a deadline, not without one.
    k, _ = await _build_kernel(
        blocking_verbs={"ticket.create"}, approval_timeout_seconds=3600
    )
    before = utcnow()
    request = await _raise_approval(k)
    assert request.timeout_at is not None
    assert before + timedelta(seconds=3600) <= request.timeout_at
    assert request.timeout_at <= utcnow() + timedelta(seconds=3600)

    # A manager built without the knob keeps the pre-timeout behaviour: no
    # deadline is stamped (the fleet's escalation lane builds its own manager).
    k2, _ = await _build_kernel(blocking_verbs={"ticket.create"})
    assert (await _raise_approval(k2)).timeout_at is None


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
async def test_respond_after_timeout_fails_409_and_expires_the_request():
    # LAZY layer, on the respond surface: a request past its timeout refuses
    # the answer with a typed 409 and leaves as TIMED_OUT - never ANSWERED.
    k, _ = await _build_kernel(blocking_verbs={"ticket.create"})
    request = await _raise_approval(k, timeout_seconds=-1)  # already overdue
    client = TestClient(create_app(k, platform={}))
    response = client.post(
        f"/v1/hitl/{request.id}/respond",
        json={"decision": "approve"},
        headers={
            "x-boltrig-tenant": TENANT,
            "x-boltrig-subject": "security-admin",
            "x-boltrig-tier": "human",
            "x-boltrig-grants": "ticket.create",
        },
    )
    assert response.status_code == 409
    assert response.json()["reason"] == "hitl_state_conflict"
    expired = await k.hitl.get(TENANT, request.id)
    assert expired.status == HITLStatus.TIMED_OUT
    assert await k.hitl.list_pending(TENANT) == []

    # An expired approval id presented to the gate cannot execute: the gate
    # raises a FRESH pause (a new request), it never reuses the dead one.
    with pytest.raises(PendingHuman) as exc:
        await k.invoke(
            "ticket", "ticket.create", {"title": "x"}, make_ctx(["ticket.create"]),
            approval_id=request.id,
        )
    assert exc.value.hitl_request_id != request.id


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
async def test_consume_refuses_a_stale_approval():
    # The human approved in time, but the gated verb did not run before the
    # deadline: the stale approval can no longer authorise the execution.
    k, _ = await _build_kernel(blocking_verbs={"ticket.create"})
    request = await _raise_approval(k, timeout_seconds=3600)
    await k.hitl.answer(TENANT, request.id, "approve", "lead@acme")
    assert (await k.hitl.get(TENANT, request.id)).status == HITLStatus.ANSWERED

    request.timeout_at = utcnow() - timedelta(seconds=1)  # deadline passes
    assert await k.hitl.consume_if_approved(
        TENANT, request.id, "ticket.create", request.request_fingerprint
    ) is False
    # The stale approval is refused, not spent: still ANSWERED, never CONSUMED.
    assert (await k.hitl.get(TENANT, request.id)).status == HITLStatus.ANSWERED


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
async def test_sweep_expires_only_overdue_requests():
    k, _ = await _build_kernel(blocking_verbs={"ticket.create"})
    await k.store.create_org(Organisation(id=TENANT, name=TENANT, slug=TENANT))
    overdue = await _raise_approval(k, timeout_seconds=-1)
    fresh = await k.hitl.create(
        tenant_id=TENANT, run_id="r", type=HITLType.APPROVAL, question="q",
        verb="ticket.create", requested_by="agent:x",
        request_fingerprint="fresh-fp", timeout_seconds=3600,
    )
    no_deadline = await k.hitl.create(
        tenant_id=TENANT, run_id="r", type=HITLType.ESCALATION, question="help?",
        verb=None, requested_by="agent:x",
    )

    assert await run_hitl_expiry_sweep(k.store) == 1
    assert (await k.hitl.get(TENANT, overdue.id)).status == HITLStatus.TIMED_OUT
    assert (await k.hitl.get(TENANT, fresh.id)).status == HITLStatus.PENDING
    assert (await k.hitl.get(TENANT, no_deadline.id)).status == HITLStatus.PENDING
    # Idempotent: nothing left overdue, the next sweep is a clean no-op.
    assert await run_hitl_expiry_sweep(k.store) == 0


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
async def test_sweep_settles_the_parked_work_item_never_a_silent_success():
    k, _ = await _build_kernel(blocking_verbs={"ticket.create"})
    await k.store.create_org(Organisation(id=TENANT, name=TENANT, slug=TENANT))
    parked = WorkItem(
        id="w-parked", tenant_id=TENANT, source="internal", intent="gated work",
        confidence=0.9, convergent=True, status=WorkStatus.AWAITING_HUMAN,
        lease_owner="worker-1", lease_expires_at=utcnow() + timedelta(hours=1),
    )
    await k.store.create_work_item(parked)
    request = await k.hitl.create(
        tenant_id=TENANT, run_id="r", type=HITLType.APPROVAL, question="q",
        verb="ticket.create", requested_by="agent:x",
        request_fingerprint="fp", work_item_id="w-parked", timeout_seconds=-1,
    )

    assert await run_hitl_expiry_sweep(k.store) == 1
    item = await k.store.get_work_item(TENANT, "w-parked")
    # The human never acted: neutral terminal CANCELLED - not DONE (no silent
    # success) and not re-queued (no approve-expire-approve loop); the lease is
    # cleared and the record says why.
    assert item.status == WorkStatus.CANCELLED
    assert item.lease_owner is None and item.lease_expires_at is None
    assert item.result == {
        "cancel_reason": "hitl_request_expired",
        "hitl_request_id": request.id,
    }

    # An item that already left AWAITING_HUMAN (resumed/finished) is untouched.
    done = WorkItem(
        id="w-done", tenant_id=TENANT, source="internal", intent="finished",
        confidence=0.9, convergent=True, status=WorkStatus.DONE,
    )
    await k.store.create_work_item(done)
    await k.hitl.create(
        tenant_id=TENANT, run_id="r", type=HITLType.APPROVAL, question="q",
        verb="ticket.create", requested_by="agent:x",
        request_fingerprint="fp2", work_item_id="w-done", timeout_seconds=-1,
    )
    assert await run_hitl_expiry_sweep(k.store) == 1
    assert (await k.store.get_work_item(TENANT, "w-done")).status == WorkStatus.DONE


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
async def test_sweep_continues_past_a_failing_tenant_and_the_loop_cancels():
    k, _ = await _build_kernel(blocking_verbs={"ticket.create"})
    await k.store.create_org(Organisation(id=TENANT, name=TENANT, slug=TENANT))
    await k.store.create_org(Organisation(id="bad-co", name="bad-co", slug="bad-co"))
    overdue = await _raise_approval(k, timeout_seconds=-1)

    real_expire = k.store.expire_hitl

    async def flaky(tenant_id, request_id):
        if tenant_id == "bad-co":
            raise RuntimeError("boom")  # this tenant blows up
        return await real_expire(tenant_id, request_id)

    # A bad-co request that is also overdue, so its expiry pass raises.
    from boltrig.models import HITLRequest, Urgency

    await k.store.create_hitl_request(
        HITLRequest(
            id="bad-req", tenant_id="bad-co", run_id="r", type=HITLType.APPROVAL,
            urgency=Urgency.BLOCKING, context="", question="q",
            verb="ticket.create", requested_by="agent:x", request_fingerprint="fp",
            timeout_at=utcnow() - timedelta(seconds=1),
        )
    )
    k.store.expire_hitl = flaky  # type: ignore[method-assign]
    # One tenant's failure is logged + skipped; acme's overdue request expires.
    assert await run_hitl_expiry_sweep(k.store) == 1
    assert (await k.hitl.get(TENANT, overdue.id)).status == HITLStatus.TIMED_OUT
    k.store.expire_hitl = real_expire  # type: ignore[method-assign]

    # The forever loop sweeps then cancels cleanly (never dies on a cycle).
    second = await _raise_approval(k, timeout_seconds=-1)
    task = asyncio.create_task(run_hitl_expiry_forever(k.store, interval=0.01))
    try:
        for _ in range(200):
            if (await k.hitl.get(TENANT, second.id)).status == HITLStatus.TIMED_OUT:
                break
            await asyncio.sleep(0.01)
        assert (await k.hitl.get(TENANT, second.id)).status == HITLStatus.TIMED_OUT
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
def test_expiry_interval_knob(monkeypatch):
    monkeypatch.delenv(INTERVAL_ENV, raising=False)
    assert hitl_expiry_interval_from_env() == DEFAULT_INTERVAL_SECONDS

    monkeypatch.setenv(INTERVAL_ENV, "300")
    assert hitl_expiry_interval_from_env() == 300.0

    monkeypatch.setenv(INTERVAL_ENV, "not-a-number")
    assert hitl_expiry_interval_from_env() == DEFAULT_INTERVAL_SECONDS

    monkeypatch.setenv(INTERVAL_ENV, "0")
    assert hitl_expiry_interval_from_env() == 0.0  # honoured as "disabled"


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
async def test_a_sweep_that_sees_no_tenants_says_so_instead_of_returning_zero(caplog):
    """The 2026-07-31 outage: the sweep went silent rather than idle.

    Every tenant is reached through ``store.list_orgs()``. Enabling RLS made that
    read return an empty list, so the per-tenant body never ran: no approval
    expired, no receipt was written, nothing was logged, and the sweep returned 0 -
    which is also its correct answer when there is simply nothing overdue.

    For nine hours SEC-14 was not being delivered and the only trace was a
    background-job receipt that had stopped advancing. A sweep that cannot see the
    fleet must not present as a quiet one.
    """
    k, _ = await _build_kernel()
    # No org is created: this reproduces exactly what RLS did to the enumeration.
    with caplog.at_level(logging.INFO, logger="boltrig.kernel.hitl_expiry"):
        assert await run_hitl_expiry_sweep(k.store) == 0

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, (
        "zero tenants produced no output at all, which is how this hid for nine hours"
    )
    message = warnings[0].getMessage()
    assert "ZERO tenants" in message
    assert "SEC-14" in message, "the message must name the property that stopped"
    assert "RLS" in message, (
        "it must name the cause that actually produced it, or the next reader takes "
        "it for an empty deployment"
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-14")
async def test_a_sweep_with_tenants_and_nothing_overdue_stays_quiet(caplog):
    """The negative control: a genuinely idle sweep must not warn.

    Without this, the guard above would pass just as well on a janitor that warns
    every cycle, and a check that cries wolf is one people learn to ignore.
    """
    k, _ = await _build_kernel()
    await k.store.create_org(Organisation(id=TENANT, name=TENANT, slug=TENANT))
    with caplog.at_level(logging.INFO, logger="boltrig.kernel.hitl_expiry"):
        assert await run_hitl_expiry_sweep(k.store) == 0
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING], (
        "an idle sweep over a real tenant list has nothing to warn about"
    )
