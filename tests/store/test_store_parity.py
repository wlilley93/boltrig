"""Store parity: InMemoryStore and PostgresStore must behave identically on the
contract the kernel relies on (SEC-15, SEC-16, SEC-14, OBS ordering).

The kernel's invariants are otherwise exercised mostly against the in-memory
store, so a divergence on the durable store (the one that ships) goes unseen
until production. This module runs ONE set of contract assertions against BOTH
backends via a parametrized fixture: the memory backend runs everywhere; the
postgres backend runs when BOLTRIG_TEST_DATABASE_URL is set (CI), and skips
cleanly offline. These cover exactly the methods most prone to drift - and the
ones recently touched: idempotency replay, the audit head/append chain, the
single-use HITL consume CAS, and newest-first list ordering.
"""

from __future__ import annotations

import os
from datetime import timedelta

import pytest

from boltrig.models import (
    ActionType,
    AuditEvent,
    HITLRequest,
    HITLStatus,
    HITLType,
    MemoryFact,
    Urgency,
    utcnow,
)

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
T = "acme"
_TABLES = (
    "nouns,verbs,verb_bindings,adapters,skills,agent_capabilities,workflow_definitions,"
    "model_endpoints,work_items,hitl_requests,hitl_responses,audit_log,budgets,"
    "idempotency_keys,credential_refs,tenant_permissions,memory_facts,"
    "security_log,audit_rollup_anchors"
)


async def _make_store(kind: str):
    if kind == "memory":
        from boltrig.store import InMemoryStore

        return InMemoryStore()
    from boltrig.store import PostgresStore

    store = await PostgresStore.connect(DSN)
    await store._pool.execute(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE")
    return store


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "postgres",
            marks=pytest.mark.skipif(
                not DSN, reason="set BOLTRIG_TEST_DATABASE_URL for Postgres parity"
            ),
        ),
    ]
)
async def store(request):
    s = await _make_store(request.param)
    yield s
    close = getattr(s, "close", None)
    if close is not None:
        await close()


# --- idempotency (SEC-15 / NFR-REL-02) -------------------------------------
@pytest.mark.store
@pytest.mark.invariant("SEC-15")
async def test_idempotency_put_then_get_roundtrips(store):
    assert await store.idempotency_get(T, "missing") is None
    await store.idempotency_put(T, "k1", {"id": "x", "n": 1})
    assert await store.idempotency_get(T, "k1") == {"id": "x", "n": 1}
    # tenant-scoped: another tenant's key space is separate
    assert await store.idempotency_get("other", "k1") is None


# --- audit chain (SEC-16) ---------------------------------------------------
def _event(seq: int, prev: str | None) -> AuditEvent:
    e = AuditEvent(
        tenant_id=T,
        run_id=f"r{seq}",
        actor="t",
        actor_tier="human",
        action_type=ActionType.TOOL_CALL,
        noun="ticket",
        verb="ticket.create",
        status="ok",
        detail={},
        ts=utcnow(),
    )
    e.seq = seq
    e.prev_hash = prev
    e.hash = f"h{seq}"
    return e


@pytest.mark.store
@pytest.mark.invariant("SEC-16")
async def test_audit_head_tracks_last_appended(store):
    assert await store.audit_head(T) == (0, None)
    await store.audit_append(_event(1, None))
    assert await store.audit_head(T) == (1, "h1")
    await store.audit_append(_event(2, "h1"))
    assert await store.audit_head(T) == (2, "h2")
    # query returns the chain in append order (oldest -> newest) so verify() can
    # re-derive it the same way on both stores.
    rows = await store.audit_query(T)
    assert [r.seq for r in rows] == [1, 2]


# --- Opbox-depth audit enrichment + security stream ([2026] VJS-COUNTY 9) ---
@pytest.mark.store
@pytest.mark.invariant("SEC-124")
async def test_audit_enrichment_and_security_stream_roundtrip_on_both_stores(store):
    from boltrig.models import AuditRollupAnchor, SecurityEvent, SecurityEventType

    # D1: the new audit fields round-trip identically (None on an un-enriched row,
    # verbatim on an enriched one) on both backends.
    plain = _event(1, None)
    enriched = _event(2, "h1")
    enriched.ip_address = "203.0.113.7"
    enriched.user_agent = "boltrig-agent/1.0"
    enriched.resource = "ticket"
    enriched.resource_id = "T-9"
    enriched.workspace_id = "ws-1"
    await store.audit_append(plain)
    await store.audit_append(enriched)
    rows = await store.audit_query(T)
    assert rows[0].ip_address is None and rows[0].workspace_id is None
    assert rows[1].ip_address == "203.0.113.7" and rows[1].user_agent == "boltrig-agent/1.0"
    assert rows[1].resource == "ticket" and rows[1].resource_id == "T-9"
    assert rows[1].workspace_id == "ws-1"

    # D3: the security stream head/append/query chain round-trips on both stores.
    assert await store.security_head(T) == (0, None)
    s1 = SecurityEvent(
        tenant_id=T, ts=utcnow(), event_type=SecurityEventType.LOGIN_FAILURE,
        reason="invalid_email_or_password", actor="eve", ip_address="1.2.3.4",
        seq=1, prev_hash=None, hash="s1",
    )
    await store.security_append(s1)
    assert await store.security_head(T) == (1, "s1")
    got = await store.security_query(T)
    assert [e.seq for e in got] == [1] and got[0].event_type == SecurityEventType.LOGIN_FAILURE
    assert await store.security_query(T, event_type="rate_limit_trip") == []

    # D4: an anchor round-trips, and latest_audit_anchor keys on (tenant, workspace).
    a = AuditRollupAnchor(
        id="anch-1", tenant_id=T, workspace_id=None, seq_start=1, seq_end=2,
        rollup_root_hash="root-abc", anchored_at=utcnow(), is_dev_fallback=True,
    )
    await store.add_audit_anchor(a)
    latest = await store.latest_audit_anchor(T)
    assert latest.id == "anch-1" and latest.seq_end == 2 and latest.is_dev_fallback is True
    assert latest.rfc3161_token is None and latest.kms_signature is None
    # a workspace-scoped anchor is a DISTINCT stream from the org-wide (NULL) one.
    assert await store.latest_audit_anchor(T, workspace_id="ws-1") is None


# --- single-use HITL consume (SEC-14) --------------------------------------
def _answered_hitl(req_id: str) -> HITLRequest:
    return HITLRequest(
        id=req_id,
        tenant_id=T,
        run_id="r1",
        type=HITLType.APPROVAL,
        urgency=Urgency.BLOCKING,
        context="c",
        question="Approve?",
        status=HITLStatus.ANSWERED,
        options=["approve", "reject"],
        verb="ticket.delete",
        requested_by="alice",
    )


@pytest.mark.store
@pytest.mark.invariant("SEC-14")
async def test_consume_hitl_is_single_use(store):
    await store.create_hitl_request(_answered_hitl("req1"))
    # first consume of an ANSWERED request succeeds (atomic ANSWERED -> CONSUMED)
    assert await store.consume_hitl(T, "req1") is True
    # second consume fails - the approval is spent (anti-replay)
    assert await store.consume_hitl(T, "req1") is False
    # an unknown request never consumes
    assert await store.consume_hitl(T, "nope") is False


# --- newest-first list ordering (OBS) --------------------------------------
def _fact(fid: str, created) -> MemoryFact:
    return MemoryFact(
        id=fid,
        tenant_id=T,
        owner_scope="tenant",
        engine_ref="local",
        kind="note",
        source_kind="manual",
        source_ref=None,
        data_class="normal",
        content=f"fact {fid}",
        created_at=created,
        redacted=False,
    )


@pytest.mark.store
@pytest.mark.invariant("SEC-33")
async def test_list_memory_facts_is_newest_first(store):
    base = utcnow()
    await store.add_memory_fact(_fact("a", base))
    await store.add_memory_fact(_fact("b", base + timedelta(seconds=1)))
    await store.add_memory_fact(_fact("c", base + timedelta(seconds=2)))
    rows = await store.list_memory_facts(T, ["tenant"])
    assert [r.id for r in rows] == ["c", "b", "a"]  # newest first on both stores


# --- workflow workspace scope round-trip ([2026] VJS-COUNTY 8, D2) ----------
@pytest.mark.store
@pytest.mark.invariant("FR-WFL-11")
async def test_workflow_workspace_id_roundtrips_on_both_stores(store):
    from boltrig.models import WorkflowDefinition, WorkflowSource

    def _wf(id: str, workspace_id: str | None) -> WorkflowDefinition:
        return WorkflowDefinition(
            id=id, tenant_id=T, version="1.0.0", source=WorkflowSource.LEARNED,
            definition={"name": id, "steps": []}, intent_tags=["billing"],
            origin_task="x", workspace_id=workspace_id,
        )

    # A SET workspace and a NULL (org-wide) workflow both round-trip identically on
    # the durable store and the in-memory one - so the application-level scope filter
    # reads the same value it wrote on either backend.
    await store.upsert_workflow(_wf("scoped", "ws-1"))
    await store.upsert_workflow(_wf("orgwide", None))
    got = {w.id: w.workspace_id for w in await store.list_workflows(T)}
    assert got == {"scoped": "ws-1", "orgwide": None}
