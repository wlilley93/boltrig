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
    HITLResponse,
    HITLStatus,
    HITLType,
    MemoryFact,
    MemoryProjectionStatus,
    Urgency,
    utcnow,
)
from boltrig.store.idempotency_contract import IdempotencyClaimStatus

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
T = "acme"
_TABLES = (
    "nouns,verbs,verb_bindings,adapters,skills,agent_capabilities,workflow_definitions,"
    "model_endpoints,work_items,hitl_requests,hitl_responses,audit_log,budgets,"
    "idempotency_keys,credential_refs,tenant_permissions,memory_facts,"
    "memory_projection_statuses,"
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
async def test_idempotency_claim_is_bound_single_owner_and_replayable(store):
    args = dict(
        actor="agent",
        on_behalf_of="alice",
        workspace_id="w1",
        noun="ticket",
        verb="ticket.create",
        request_hash="sha256-request",
        lease_seconds=60,
    )
    first = await store.idempotency_claim(T, "k1", owner_token="owner-1", **args)
    concurrent = await store.idempotency_claim(T, "k1", owner_token="owner-2", **args)
    mismatch = await store.idempotency_claim(
        T, "k1", owner_token="owner-3", **{**args, "actor": "other"}
    )
    assert first.status == IdempotencyClaimStatus.ACQUIRED
    assert concurrent.status == IdempotencyClaimStatus.IN_PROGRESS
    assert mismatch.status == IdempotencyClaimStatus.MISMATCH
    assert await store.idempotency_start(T, "k1", "owner-1", 60)
    assert await store.idempotency_complete(T, "k1", "owner-1", {"id": "x"})
    replay = await store.idempotency_claim(T, "k1", owner_token="owner-4", **args)
    assert replay.status == IdempotencyClaimStatus.COMPLETED
    assert replay.result == {"id": "x"}
    other = await store.idempotency_claim("other", "k1", owner_token="owner", **args)
    assert other.status == IdempotencyClaimStatus.ACQUIRED


@pytest.mark.store
@pytest.mark.invariant("SEC-15")
async def test_idempotency_expiry_reclaims_only_before_execution(store):
    args = dict(
        actor="agent",
        on_behalf_of=None,
        workspace_id=None,
        noun="workflow",
        verb="workflow.trigger",
        request_hash="request",
        lease_seconds=0,
    )
    first = await store.idempotency_claim(T, "lease", owner_token="owner-1", **args)
    reclaimed = await store.idempotency_claim(T, "lease", owner_token="owner-2", **args)
    assert first.status == reclaimed.status == IdempotencyClaimStatus.ACQUIRED
    assert await store.idempotency_start(T, "lease", "owner-2", 0)
    expired = await store.idempotency_claim(T, "lease", owner_token="owner-3", **args)
    assert expired.status == IdempotencyClaimStatus.UNCERTAIN
    assert not await store.idempotency_start(T, "lease", "owner-3", 60)


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
        tenant_id=T,
        ts=utcnow(),
        event_type=SecurityEventType.LOGIN_FAILURE,
        reason="invalid_email_or_password",
        actor="eve",
        ip_address="1.2.3.4",
        seq=1,
        prev_hash=None,
        hash="s1",
    )
    await store.security_append(s1)
    assert await store.security_head(T) == (1, "s1")
    got = await store.security_query(T)
    assert [e.seq for e in got] == [1] and got[0].event_type == SecurityEventType.LOGIN_FAILURE
    assert await store.security_query(T, event_type="rate_limit_trip") == []

    # D4: an anchor round-trips, and latest_audit_anchor keys on (tenant, workspace).
    a = AuditRollupAnchor(
        id="anch-1",
        tenant_id=T,
        workspace_id=None,
        seq_start=1,
        seq_end=2,
        rollup_root_hash="root-abc",
        anchored_at=utcnow(),
        is_dev_fallback=True,
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
        requested_on_behalf_of="owner",
        request_fingerprint="delete-fingerprint",
    )


def _pending_hitl(req_id: str) -> HITLRequest:
    req = _answered_hitl(req_id)
    req.status = HITLStatus.PENDING
    return req


def _response(req_id: str, resp_id: str = "resp1") -> HITLResponse:
    return HITLResponse(
        id=resp_id,
        request_id=req_id,
        tenant_id=T,
        decision="approve",
        respondent="lead@acme",
        responded_at=utcnow(),
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


@pytest.mark.store
@pytest.mark.invariant("SEC-14")
async def test_hitl_request_binding_round_trips(store):
    expected = _pending_hitl("req-bound")
    await store.create_hitl_request(expected)
    actual = await store.get_hitl_request(T, expected.id)
    assert actual.requested_on_behalf_of == "owner"
    assert actual.request_fingerprint == "delete-fingerprint"


@pytest.mark.store
@pytest.mark.invariant("SEC-14")
async def test_answer_hitl_only_transitions_pending_requests(store):
    await store.create_hitl_request(_pending_hitl("req-answer"))
    assert await store.answer_hitl(_response("req-answer")) is not None
    # Once answered, a second answer is refused and does not create a new response.
    assert await store.answer_hitl(_response("req-answer", "resp2")) is None
    assert await store.consume_hitl(T, "req-answer") is True
    # Once consumed, it still cannot be answered back into an authorizing state.
    assert await store.answer_hitl(_response("req-answer", "resp3")) is None
    assert await store.consume_hitl(T, "req-answer") is False


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


@pytest.mark.store
async def test_memory_projection_status_upserts_and_filters_on_both_stores(store):
    base = utcnow()
    row = MemoryProjectionStatus(
        id="mem0:remember:f1",
        tenant_id=T,
        projection_id="mem0",
        operation="remember",
        status="pending",
        fact_id="f1",
        created_at=base,
        updated_at=base,
    )
    await store.upsert_memory_projection_status(row)
    await store.upsert_memory_projection_status(
        MemoryProjectionStatus(**{**row.__dict__, "status": "written", "projection_ref": "mem0:f1"})
    )
    await store.upsert_memory_projection_status(
        MemoryProjectionStatus(
            id="cognee:remember:f2",
            tenant_id=T,
            projection_id="cognee",
            operation="remember",
            status="failed",
            fact_id="f2",
            error="down",
            created_at=base,
            updated_at=base + timedelta(seconds=1),
        )
    )

    rows = await store.list_memory_projection_statuses(T, fact_id="f1")
    assert [(r.projection_id, r.status, r.projection_ref) for r in rows] == [
        ("mem0", "written", "mem0:f1")
    ]
    assert [r.fact_id for r in await store.list_memory_projection_statuses(T)] == ["f2", "f1"]


# --- workflow workspace scope round-trip ([2026] VJS-COUNTY 8, D2) ----------
@pytest.mark.store
@pytest.mark.invariant("FR-WFL-11")
async def test_workflow_workspace_id_roundtrips_on_both_stores(store):
    from boltrig.models import WorkflowDefinition, WorkflowSource

    def _wf(id: str, workspace_id: str | None) -> WorkflowDefinition:
        return WorkflowDefinition(
            id=id,
            tenant_id=T,
            version="1.0.0",
            source=WorkflowSource.LEARNED,
            definition={"name": id, "steps": []},
            intent_tags=["billing"],
            origin_task="x",
            workspace_id=workspace_id,
        )

    # A SET workspace and a NULL (org-wide) workflow both round-trip identically on
    # the durable store and the in-memory one - so the application-level scope filter
    # reads the same value it wrote on either backend.
    await store.upsert_workflow(_wf("scoped", "ws-1"))
    await store.upsert_workflow(_wf("orgwide", None))
    got = {w.id: w.workspace_id for w in await store.list_workflows(T)}
    assert got == {"scoped": "ws-1", "orgwide": None}


@pytest.mark.store
@pytest.mark.invariant("FR-WFL-18")
async def test_list_workflows_returns_latest_version_per_id_on_both_stores(store):
    from boltrig.models import WorkflowDefinition, WorkflowSource

    def _wf(version: str, name: str) -> WorkflowDefinition:
        return WorkflowDefinition(
            id="wf-versioned",
            tenant_id=T,
            version=version,
            source=WorkflowSource.LEARNED,
            definition={"name": name, "steps": []},
            intent_tags=["billing"],
            origin_task="x",
        )

    # Two versions of ONE workflow id. list_workflows returns exactly one row for
    # that id (the latest version), identically on the durable and in-memory stores,
    # so a caller matching a workflow by id never sees a duplicate or stale version.
    await store.upsert_workflow(_wf("1.0.0", "v1"))
    await store.upsert_workflow(_wf("2.0.0", "v2"))
    rows = [w for w in await store.list_workflows(T) if w.id == "wf-versioned"]
    assert len(rows) == 1
    assert rows[0].version == "2.0.0"
    assert rows[0].definition["name"] == "v2"
