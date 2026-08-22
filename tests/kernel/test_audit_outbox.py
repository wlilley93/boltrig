"""The durable audit outbox (SEC-16 audit-always).

An AuditWriter.append fault must not cost the event: the payload is deferred to
the outbox, and the janitor re-chains it against the then-current head once the
fault clears - seq/hash re-derived at drain time, so the chain stays contiguous
and verify() passes over the drained row. The event's ts preserves the ACTION
time and its detail carries an honest ``outbox_deferred`` marker."""

from __future__ import annotations

from datetime import timedelta

import pytest

from boltrig.kernel.audit import AuditWriter, audit_event_from_payload
from boltrig.kernel.audit_outbox import (
    audit_outbox_interval_from_env,
    drain_tenant_once,
    run_audit_outbox_sweep,
)
from boltrig.models import ActionType, AuditEvent, Organisation, utcnow
from boltrig.store import InMemoryStore

T = "acme"


def _event(noun: str = "ticket", verb: str = "ticket.create", ts=None) -> AuditEvent:
    return AuditEvent(
        tenant_id=T,
        ts=ts or utcnow(),
        actor="ephemeral-1",
        actor_tier="ephemeral",
        action_type=ActionType.TOOL_CALL,
        noun=noun,
        verb=verb,
        status="ok",
        detail={"params": {"title": "x"}},
    )


async def _org(store):
    await store.create_org(Organisation(id=T, name=T, slug=T))


@pytest.mark.kernel
@pytest.mark.invariant("SEC-16")
async def test_a_failed_append_defers_instead_of_dropping(monkeypatch):
    store = InMemoryStore()
    await _org(store)
    writer = AuditWriter(store)
    original_ts = utcnow() - timedelta(minutes=5)

    async def _failing_append(event):
        raise RuntimeError("transient db fault")

    monkeypatch.setattr(store, "audit_append", _failing_append)
    event = await writer.write(_event(ts=original_ts))

    # No raise, no chain fields, and the payload is durably held.
    assert event.seq is None and event.hash is None
    due = await store.audit_outbox_due(T, utcnow())
    assert len(due) == 1
    payload = due[0]["payload"]
    assert payload["ts"] == original_ts.isoformat()  # the ACTION time survives
    assert payload["detail"]["outbox_deferred"]["append_error"] == "RuntimeError"


@pytest.mark.kernel
@pytest.mark.invariant("SEC-16")
async def test_the_janitor_rechains_deferred_events_and_the_chain_verifies(monkeypatch):
    store = InMemoryStore()
    await _org(store)
    writer = AuditWriter(store)

    async def _failing_append(event):
        raise RuntimeError("transient db fault")

    monkeypatch.setattr(store, "audit_append", _failing_append)
    await writer.write(_event(verb="ticket.create"))
    monkeypatch.undo()

    # A healthy append lands while the first event sits deferred...
    await writer.write(_event(verb="ticket.update"))

    drained, deferred = await drain_tenant_once(writer, store, T)
    assert (drained, deferred) == (1, 0)
    assert await store.audit_outbox_due(T, utcnow()) == []

    rows = await store.audit_query(T, limit=10)
    by_verb = {r.verb: r for r in rows}
    # The deferred event re-chained at the CURRENT head (seq 2), ts preserved,
    # and its detail honestly records the deferral.
    assert by_verb["ticket.create"].seq == 2
    assert "outbox_deferred" in by_verb["ticket.create"].detail
    assert by_verb["ticket.update"].seq == 1
    ok, bad = await writer.verify(T)
    assert ok and bad is None, "the drained chain must verify whole"


@pytest.mark.kernel
@pytest.mark.invariant("SEC-16")
async def test_a_persistent_fault_backs_off_and_keeps_the_row(monkeypatch):
    store = InMemoryStore()
    await _org(store)
    writer = AuditWriter(store)

    async def _failing_append(event):
        raise RuntimeError("still down")

    monkeypatch.setattr(store, "audit_append", _failing_append)
    await writer.write(_event())
    drained, deferred = await drain_tenant_once(writer, store, T)
    assert (drained, deferred) == (0, 1)
    row = (await store.audit_outbox_due(T, utcnow() + timedelta(hours=1)))[0]
    assert row["attempts"] == 1 and row["append_error"] == "RuntimeError"


@pytest.mark.kernel
@pytest.mark.invariant("SEC-16")
async def test_the_sweep_drains_every_tenant_and_survives_one_bad_tenant():
    store = InMemoryStore()
    await _org(store)
    writer = AuditWriter(store)
    await writer.write(_event())
    await writer.write(_event(verb="ticket.close"))
    # The sweep over orgs with a healthy chain drains nothing and P9s on.
    assert await run_audit_outbox_sweep(store, writer=writer) == 0


@pytest.mark.kernel
async def test_payload_roundtrip_preserves_fields_and_ignores_chain_state():
    event = _event()
    event.seq = 999
    event.prev_hash = "stale"
    event.hash = "stale"
    rebuilt = audit_event_from_payload(
        {
            "tenant_id": event.tenant_id,
            "ts": event.ts.isoformat(),
            "actor": event.actor,
            "action_type": event.action_type.value,
            "status": event.status,
            "noun": event.noun,
            "verb": event.verb,
            "detail": {"params": {"title": "x"}},
            "unknown_future_key": "dropped",
        }
    )
    assert rebuilt.tenant_id == event.tenant_id and rebuilt.verb == event.verb
    assert rebuilt.ts == event.ts
    assert rebuilt.seq is None and rebuilt.hash is None


def test_interval_env_reads_and_defaults(monkeypatch):
    assert audit_outbox_interval_from_env({}) == 60.0
    monkeypatch.setenv("BOLTRIG_AUDIT_OUTBOX_INTERVAL", "5")
    assert audit_outbox_interval_from_env() == 5.0
    monkeypatch.setenv("BOLTRIG_AUDIT_OUTBOX_INTERVAL", "0")
    assert audit_outbox_interval_from_env() == 0.0
