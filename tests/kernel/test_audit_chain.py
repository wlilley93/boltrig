"""Audit is append-only, hash-chained, and tamper-evident (SEC-16, K-19)."""

import asyncio

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
@pytest.mark.invariant("SEC-16")
async def test_concurrent_writes_keep_a_contiguous_verifiable_chain():
    # On Postgres, audit_head and audit_append are separate awaited round-trips,
    # so two concurrent same-tenant writes can both read head=N and claim seq=N+1
    # - colliding on UNIQUE(tenant_id, seq) or forking the hash chain. The
    # in-memory store never suspends between the two, so to exercise the race
    # deterministically we subclass it with a head read that yields control. The
    # writer must serialise per tenant so the chain stays contiguous regardless.
    from boltrig.kernel.audit import AuditWriter
    from boltrig.models import ActionType, AuditEvent
    from boltrig.store import InMemoryStore

    class YieldingStore(InMemoryStore):
        async def audit_head(self, tenant_id):
            head = await super().audit_head(tenant_id)
            await asyncio.sleep(0)  # force a scheduler yield between head and append
            return head

    store = YieldingStore()
    writer = AuditWriter(store)

    def _event(i: int) -> AuditEvent:
        return AuditEvent(
            tenant_id=TENANT,
            run_id=f"r{i}",
            actor="tester",
            actor_tier="human",
            action_type=ActionType.TOOL_CALL,
            noun="ticket",
            verb="ticket.create",
            status="ok",
            detail={},
            ts=None,
        )

    n = 24
    await asyncio.gather(*[writer.write(_event(i)) for i in range(n)])

    events = await store.audit_query(TENANT, limit=10_000)
    seqs = sorted(e.seq for e in events)
    assert seqs == list(range(1, len(events) + 1))  # contiguous, no dup/gap
    ok, bad = await writer.verify(TENANT)
    assert ok and bad is None


async def _long_chain(n: int):
    """A REAL hash-chained audit trail of n rows on a fresh in-memory store."""
    from boltrig.kernel.audit import AuditWriter
    from boltrig.models import ActionType, AuditEvent
    from boltrig.store import InMemoryStore

    store = InMemoryStore()
    writer = AuditWriter(store)
    for i in range(n):
        await writer.write(AuditEvent(
            tenant_id=TENANT, run_id=f"r{i}", actor="t", actor_tier="human",
            action_type=ActionType.TOOL_CALL, noun="ticket", verb="ticket.create",
            status="ok", detail={}, ts=None,
        ))
    return store, writer


@pytest.mark.kernel
@pytest.mark.invariant("SEC-168")
async def test_a_chain_longer_than_the_old_window_verifies_ok():
    # SEC-168 false-positive regression: verify() once read only the newest 10_000
    # rows and seeded prev=None, so the window's first row (whose prev_hash points
    # at a row OUTSIDE the window) "failed" on a completely untampered chain.
    _store, writer = await _long_chain(10_050)
    assert await writer.verify(TENANT) == (True, None)


@pytest.mark.kernel
@pytest.mark.invariant("SEC-168")
async def test_tampering_below_the_old_window_is_still_caught():
    # SEC-168 false-negative regression: rows below any tail window were never
    # re-derived, so tampering an OLD row went unseen. seq 5 sits 10_045 rows from
    # the head - far below the old 10_000-row window.
    store, writer = await _long_chain(10_050)
    next(e for e in store._audit[TENANT] if e.seq == 5).status = "tampered"
    assert await writer.verify(TENANT) == (False, 5)


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
