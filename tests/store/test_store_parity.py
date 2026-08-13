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

import asyncio
import json
import os
from dataclasses import replace
from datetime import timedelta

import pytest

from boltrig.models import (
    ActionType,
    AdapterRecord,
    AgentCapability,
    AuditEvent,
    Channel,
    Conversation,
    EvalCase,
    EvalRun,
    HITLRequest,
    HITLResponse,
    HITLStatus,
    HITLType,
    MemoryFact,
    MemoryProjectionStatus,
    ModelEndpoint,
    Noun,
    RealtimeCallEvent,
    RealtimeCallSession,
    SecurityEvent,
    SecurityEventType,
    Skill,
    TargetType,
    Urgency,
    Verb,
    VerbBinding,
    WorkItem,
    WorkStatus,
    utcnow,
)
from boltrig.store.idempotency_contract import IdempotencyClaimStatus
from boltrig.store.work_mutations import (
    WorkMutationConflict,
    governed_create_work,
    governed_mutate_work,
)

DSN = os.environ.get("BOLTRIG_TEST_DATABASE_URL")
T = "acme"
_TABLES = (
    "nouns,verbs,verb_bindings,adapters,skills,agent_capabilities,workflow_definitions,"
    "model_endpoints,eval_runs,eval_cases,work_items,hitl_requests,hitl_responses,"
    "audit_log,budget_usage,budgets,"
    "idempotency_keys,credential_refs,tenant_permissions,memory_facts,"
    "memory_projection_statuses,"
    "integration_connections,integration_catalogue,"
    "security_log,audit_rollup_anchors,conversations,channels,realtime_calls,"
    "realtime_call_events"
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


@pytest.mark.store
@pytest.mark.invariant("SEC-22")
async def test_generated_adapter_projection_roundtrips_on_both_stores(store):
    from boltrig.adapters.generator import generate_adapter_from_spec
    from boltrig.config.control_generated_adapter import (
        generated_adapter_from_record,
        generated_adapter_projection,
    )

    generated = generate_adapter_from_spec(
        {
            "openapi": "3.0.0",
            "info": {"title": "Durable", "version": "1"},
            "servers": [{"url": "https://durable.example.test/v1"}],
            "paths": {
                "/things/{id}": {
                    "get": {
                        "operationId": "thing.read",
                        "parameters": [
                            {
                                "name": "id",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string"},
                            }
                        ],
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
        },
        adapter_id="durable-generated",
    )
    projection = generated_adapter_projection(generated)
    assert await store.create_adapter_if_absent(
        AdapterRecord(
            id=generated.id,
            tenant_id=T,
            version=generated.version,
            runtime=generated.runtime,
            source="generated",
            module_ref=type(generated).__module__,
            spec_ref=projection,
            created_by="author",
            activated=True,
        )
    )
    stored = await store.get_adapter(T, generated.id)
    assert stored is not None
    assert stored.spec_ref == projection
    rebuilt = generated_adapter_from_record(stored)
    assert rebuilt.activated is True
    assert rebuilt.render_source() == generated.render_source()
    assert [item.verb_id for item in rebuilt.describe()] == ["thing.read"]


@pytest.mark.store
@pytest.mark.invariant("SEC-WRK-17")
async def test_governed_work_graph_and_lease_fence_match_on_both_stores(store):
    root = await governed_create_work(
        store,
        WorkItem(
            id="governed-root",
            tenant_id=T,
            workspace_id="workspace-a",
            source="internal",
            intent="Root",
            confidence=1.0,
            convergent=True,
            owner_member="engineering",
        ),
        workspace_id="workspace-a",
        departments=None,
    )
    child = await governed_create_work(
        store,
        WorkItem(
            id="governed-child",
            tenant_id=T,
            workspace_id="workspace-a",
            source="internal",
            intent="Child",
            confidence=1.0,
            convergent=True,
            owner_member="engineering",
            parent_id=root.id,
        ),
        workspace_id="workspace-a",
        departments=None,
    )
    grandchild = await governed_create_work(
        store,
        WorkItem(
            id="governed-grandchild",
            tenant_id=T,
            workspace_id="workspace-a",
            source="internal",
            intent="Grandchild",
            confidence=1.0,
            convergent=True,
            owner_member="engineering",
            parent_id=child.id,
        ),
        workspace_id="workspace-a",
        departments=None,
    )

    moved = await governed_mutate_work(
        store,
        T,
        child.id,
        action="reparent",
        value=None,
        workspace_id="workspace-a",
        departments=None,
    )
    assert moved.depth == 0 and moved.parent_id is None
    assert (await store.get_work_item(T, grandchild.id)).depth == 1

    with pytest.raises(ValueError, match="cycle"):
        await governed_mutate_work(
            store,
            T,
            child.id,
            action="reparent",
            value=grandchild.id,
            workspace_id="workspace-a",
            departments=None,
        )

    leased = await store.get_work_item(T, grandchild.id)
    leased.lease_owner = "worker"
    leased.lease_expires_at = utcnow() + timedelta(minutes=5)
    await store.update_work_item(leased)
    with pytest.raises(WorkMutationConflict, match="leased"):
        await governed_mutate_work(
            store,
            T,
            grandchild.id,
            action="assign",
            value="operations",
            workspace_id="workspace-a",
            departments=None,
        )
    with pytest.raises(WorkMutationConflict, match="leased"):
        await governed_mutate_work(
            store,
            T,
            child.id,
            action="reparent",
            value=root.id,
            workspace_id="workspace-a",
            departments=None,
        )
    with pytest.raises(ValueError, match="illegal manual transition"):
        await governed_mutate_work(
            store,
            T,
            child.id,
            action="status",
            value=WorkStatus.DONE,
            workspace_id="workspace-a",
            departments=None,
        )

    depth_limit = WorkItem(
        id="governed-depth-limit",
        tenant_id=T,
        workspace_id="workspace-a",
        source="internal",
        intent="Depth limit",
        confidence=1.0,
        convergent=True,
        owner_member="engineering",
        depth=32,
    )
    await store.create_work_item(depth_limit)
    with pytest.raises(ValueError, match="depth limit"):
        await governed_create_work(
            store,
            WorkItem(
                id="governed-too-deep",
                tenant_id=T,
                workspace_id="workspace-a",
                source="internal",
                intent="Too deep",
                confidence=1.0,
                convergent=True,
                owner_member="engineering",
                parent_id=depth_limit.id,
            ),
            workspace_id="workspace-a",
            departments=None,
        )


# --- model endpoint lifecycle (SEC-WRK-14) ----------------------------------
@pytest.mark.store
@pytest.mark.invariant("SEC-WRK-14")
async def test_model_endpoint_lifecycle_matches_on_both_stores(store):
    endpoint = ModelEndpoint(
        id="recoverable-model",
        tenant_id=T,
        kind="openai",
        model="model-a",
        base_url="https://models.example.test/v1",
        fallback=None,
        data_class="standard",
    )
    await store.upsert_model_endpoint(endpoint)
    retired = await store.set_model_endpoint_active(T, endpoint.id, False)
    assert retired is not None and retired.is_active is False

    await store.upsert_model_endpoint(
        ModelEndpoint(
            id=endpoint.id,
            tenant_id=T,
            kind="openai",
            model="model-b",
            base_url="https://replacement.example.test/v1",
            fallback=None,
            data_class="standard",
        )
    )
    edited = await store.get_model_endpoint(T, endpoint.id)
    assert edited is not None
    assert edited.model == "model-b"
    assert edited.base_url == "https://replacement.example.test/v1"
    assert edited.is_active is False
    assert [(item.id, item.is_active) for item in await store.list_model_endpoints(T)] == [
        (endpoint.id, False)
    ]

    restored = await store.set_model_endpoint_active(T, endpoint.id, True)
    assert restored is not None and restored.is_active is True


@pytest.mark.store
@pytest.mark.invariant("SEC-WRK-14")
async def test_model_endpoint_revision_cas_serializes_competing_writers_on_both_stores(
    store,
):
    first = ModelEndpoint(
        id="create-race",
        tenant_id=T,
        kind="bifrost",
        model="provider/model-a-20260812",
        base_url=None,
        fallback=None,
        data_class="standard",
    )
    second = replace(first, model="provider/model-b-20260812")
    create_references = await store.model_endpoint_references(T, first.id)
    created = await asyncio.gather(
        store.compare_and_upsert_model_endpoint(
            first,
            None,
            expected_fallback=None,
            expected_references=create_references,
        ),
        store.compare_and_upsert_model_endpoint(
            second,
            None,
            expected_fallback=None,
            expected_references=create_references,
        ),
    )
    assert sorted(created) == [False, True]

    current = await store.get_model_endpoint(T, first.id)
    assert current is not None
    edited = replace(current, model="provider/model-c-20260812")
    current_references = await store.model_endpoint_references(T, current.id)
    edit_won, lifecycle_row = await asyncio.gather(
        store.compare_and_upsert_model_endpoint(
            edited,
            current,
            expected_fallback=None,
            expected_references=current_references,
        ),
        store.compare_and_set_model_endpoint_active(T, current.id, False, current),
    )
    assert (edit_won, lifecycle_row is not None) in {(True, False), (False, True)}

    fallback = ModelEndpoint(
        id="fallback-race",
        tenant_id=T,
        kind="bifrost",
        model="provider/model-fallback-20260812",
        base_url=None,
        fallback=None,
        data_class="standard",
    )
    await store.upsert_model_endpoint(fallback)
    fallback = await store.get_model_endpoint(T, fallback.id)
    assert fallback is not None
    primary = replace(first, id="primary-race", fallback=fallback.id)
    primary_references = await store.model_endpoint_references(T, primary.id)
    primary_won, fallback_row = await asyncio.gather(
        store.compare_and_upsert_model_endpoint(
            primary,
            None,
            expected_fallback=fallback,
            expected_references=primary_references,
        ),
        store.compare_and_set_model_endpoint_active(
            T, fallback.id, False, fallback
        ),
    )
    assert (primary_won, fallback_row is not None) in {(True, False), (False, True)}


@pytest.mark.store
@pytest.mark.invariant("SEC-WRK-14")
async def test_model_endpoint_reference_cas_rejects_capability_drift_and_aba_on_both_stores(
    store,
):
    other_tenant = f"{T}-other"
    target = ModelEndpoint(
        id="capability-reference-target",
        tenant_id=T,
        kind="local",
        model="model-before-reference-drift",
        modalities=("text", "vision"),
    )
    other = replace(target, id="other-capability-target", model="other-model")
    await store.upsert_model_endpoint(target)
    await store.upsert_model_endpoint(other)
    await store.upsert_model_endpoint(
        replace(target, tenant_id=other_tenant, model="other-tenant-model")
    )
    await store.upsert_capability(
        AgentCapability(
            name="foreign-reference",
            tenant_id=other_tenant,
            runtime="codex",
            supported_skills=["*"],
            max_depth=1,
            is_ephemeral=True,
            cost_tier="standard",
            model_endpoint=target.id,
        )
    )
    approved_endpoint = await store.get_model_endpoint(T, target.id)
    assert approved_endpoint is not None
    approved_references = await store.model_endpoint_references(T, target.id)
    assert approved_references.approval_context() == {
        "capabilities": [],
        "fallbacks": [],
    }

    capability = AgentCapability(
        name="new-reference",
        tenant_id=T,
        runtime="codex",
        supported_skills=["*"],
        max_depth=1,
        is_ephemeral=True,
        cost_tier="standard",
        model_endpoint=target.id,
    )
    await store.upsert_capability(capability)
    after_add = await store.get_model_endpoint(T, target.id)
    assert after_add is not None
    assert after_add.revision == approved_endpoint.revision + 1
    added_references = await store.model_endpoint_references(T, target.id)
    assert added_references.approval_context()["capabilities"] == ["new-reference"]
    assert not await store.compare_and_upsert_model_endpoint(
        replace(after_add, model="stale-reference-edit"),
        after_add,
        expected_fallback=None,
        expected_references=approved_references,
    )

    await store.upsert_capability(replace(capability, model_endpoint=other.id))
    after_remove = await store.get_model_endpoint(T, target.id)
    assert after_remove is not None
    assert after_remove.revision == after_add.revision + 1
    removed_references = await store.model_endpoint_references(T, target.id)
    assert removed_references == approved_references
    assert not await store.compare_and_upsert_model_endpoint(
        replace(approved_endpoint, model="aba-reference-edit"),
        approved_endpoint,
        expected_fallback=None,
        expected_references=approved_references,
    )
    assert await store.compare_and_upsert_model_endpoint(
        replace(after_remove, model="current-reference-edit"),
        after_remove,
        expected_fallback=None,
        expected_references=removed_references,
    )


@pytest.mark.store
@pytest.mark.invariant("SEC-WRK-14")
async def test_generic_model_route_is_an_endpoint_reference_on_both_stores(store):
    endpoint = ModelEndpoint(
        id="generic-voice-reference",
        tenant_id=T,
        kind="xai",
        model="voice-model",
        modalities=("realtime",),
    )
    await store.upsert_model_endpoint(endpoint)
    await store.upsert_capability(
        AgentCapability(
            name="voice-reference-agent",
            tenant_id=T,
            runtime="codex",
            supported_skills=["*"],
            max_depth=1,
            is_ephemeral=True,
            cost_tier="standard",
            model_routes={"realtime": endpoint.id},
        )
    )

    references = await store.model_endpoint_references(T, endpoint.id)
    assert references.approval_context() == {
        "capabilities": ["voice-reference-agent"],
        "fallbacks": [],
    }


@pytest.mark.store
@pytest.mark.invariant("SEC-WRK-14")
async def test_legacy_double_encoded_model_routes_use_exact_values_on_postgres(store):
    pool = getattr(store, "_pool", None)
    if pool is None:
        pytest.skip("PostgreSQL JSONB compatibility regression")

    for endpoint_id in ("text", "actual-route"):
        await store.upsert_model_endpoint(
            ModelEndpoint(
                id=endpoint_id,
                tenant_id=T,
                kind="local",
                model=f"{endpoint_id}-model",
                modalities=("text",),
            )
        )
    # The old writer passed json.dumps(...) into a codec which serialized it a
    # second time. The durable row is therefore a JSON string containing an
    # object. An endpoint named "text" must not match the object's key; only the
    # exact route VALUE is a reference. A malformed historical string must also
    # remain harmless and non-referencing.
    await pool.execute(
        """INSERT INTO agent_capabilities
             (name, tenant_id, runtime, model_routes, supported_skills,
              max_depth, is_ephemeral, cost_tier, source, is_active)
           VALUES ($1,$2,'codex',$3::jsonb,$4,1,true,'standard',
                   'control-plane',true),
                  ($5,$2,'codex',$6::jsonb,$4,1,true,'standard',
                   'control-plane',true)""",
        "legacy-double-encoded",
        T,
        json.dumps({"text": "actual-route"}),
        ["*"],
        "legacy-malformed",
        "not-an-object",
    )

    assert (
        await store.model_endpoint_references(T, "text")
    ).approval_context()["capabilities"] == []
    assert (
        await store.model_endpoint_references(T, "actual-route")
    ).approval_context()["capabilities"] == ["legacy-double-encoded"]


@pytest.mark.store
@pytest.mark.invariant("SEC-WRK-14")
async def test_model_endpoint_edit_and_new_reference_are_totally_ordered_on_both_stores(
    store,
):
    endpoint = ModelEndpoint(
        id="concurrent-reference-target",
        tenant_id=T,
        kind="local",
        model="model-before-concurrency",
        modalities=("text", "vision"),
    )
    await store.upsert_model_endpoint(endpoint)
    approved_endpoint = await store.get_model_endpoint(T, endpoint.id)
    assert approved_endpoint is not None
    approved_references = await store.model_endpoint_references(T, endpoint.id)
    capability = AgentCapability(
        name="concurrent-reference",
        tenant_id=T,
        runtime="codex",
        supported_skills=["*"],
        max_depth=1,
        is_ephemeral=True,
        cost_tier="standard",
        model_endpoint=endpoint.id,
    )

    edit_won, _ = await asyncio.gather(
        store.compare_and_upsert_model_endpoint(
            replace(approved_endpoint, model="model-after-concurrency"),
            approved_endpoint,
            expected_fallback=None,
            expected_references=approved_references,
        ),
        store.upsert_capability(capability),
    )

    current = await store.get_model_endpoint(T, endpoint.id)
    assert current is not None
    assert (
        await store.model_endpoint_references(T, endpoint.id)
    ).approval_context()["capabilities"] == [capability.name]
    if edit_won:
        # Endpoint CAS linearized first; the later reference write bumped the
        # revision again, so an older approval can never mistake this for its
        # reviewed endpoint state.
        assert current.model == "model-after-concurrency"
        assert current.revision == approved_endpoint.revision + 2
    else:
        # Reference insertion linearized first and invalidated the endpoint CAS.
        assert current.model == "model-before-concurrency"
        assert current.revision == approved_endpoint.revision + 1


@pytest.mark.store
@pytest.mark.invariant("SEC-WRK-14")
async def test_model_endpoint_reference_cas_rejects_fallback_drift_and_aba_on_both_stores(
    store,
):
    other_tenant = f"{T}-other"
    target = ModelEndpoint(
        id="fallback-reference-target",
        tenant_id=T,
        kind="local",
        model="model-before-fallback-drift",
    )
    await store.upsert_model_endpoint(target)
    await store.upsert_model_endpoint(
        replace(target, tenant_id=other_tenant, model="other-tenant-model")
    )
    await store.upsert_model_endpoint(
        replace(
            target,
            id="foreign-fallback-reference",
            tenant_id=other_tenant,
            fallback=target.id,
        )
    )
    await store.upsert_model_endpoint(
        replace(target, id="z-fallback-reference", fallback=target.id)
    )
    await store.upsert_model_endpoint(
        replace(target, id="a-fallback-reference", fallback=target.id)
    )
    approved_endpoint = await store.get_model_endpoint(T, target.id)
    assert approved_endpoint is not None
    approved_references = await store.model_endpoint_references(T, target.id)
    assert approved_references.approval_context() == {
        "capabilities": [],
        "fallbacks": ["a-fallback-reference", "z-fallback-reference"],
    }

    dependent = await store.get_model_endpoint(T, "a-fallback-reference")
    assert dependent is not None
    await store.upsert_model_endpoint(replace(dependent, fallback=None))
    after_remove = await store.get_model_endpoint(T, target.id)
    assert after_remove is not None
    removed_references = await store.model_endpoint_references(T, target.id)
    assert removed_references.approval_context()["fallbacks"] == [
        "z-fallback-reference"
    ]
    assert not await store.compare_and_upsert_model_endpoint(
        replace(after_remove, model="stale-fallback-edit"),
        after_remove,
        expected_fallback=None,
        expected_references=approved_references,
    )

    await store.upsert_model_endpoint(replace(dependent, fallback=target.id))
    rebound = await store.get_model_endpoint(T, "a-fallback-reference")
    assert rebound is not None
    await store.upsert_model_endpoint(replace(rebound, fallback=None))
    after_aba = await store.get_model_endpoint(T, target.id)
    assert after_aba is not None
    assert await store.model_endpoint_references(T, target.id) == removed_references
    assert not await store.compare_and_upsert_model_endpoint(
        replace(after_remove, model="aba-fallback-edit"),
        after_remove,
        expected_fallback=None,
        expected_references=removed_references,
    )
    assert await store.compare_and_upsert_model_endpoint(
        replace(after_aba, model="current-fallback-edit"),
        after_aba,
        expected_fallback=None,
        expected_references=removed_references,
    )


# --- evaluation case lifecycle (SEC-WRK-18) --------------------------------
@pytest.mark.store
@pytest.mark.invariant("SEC-WRK-18")
async def test_eval_case_lifecycle_matches_on_both_stores(store):
    case = EvalCase(
        id="recoverable-eval",
        tenant_id=T,
        target_kind="skill",
        target_ref="review",
        input={"task": "review first"},
        assertions={"must_not_call": ["record.delete"]},
        labels=["regression"],
    )
    await store.upsert_eval_case(case)
    historical = EvalRun(
        id="historical-run",
        tenant_id=T,
        case_id=case.id,
        passed=True,
        score=1.0,
        run_id="fleet-run",
        detail={"checks": {"safe": True}},
    )
    await store.add_eval_run(historical)

    assert await store.set_eval_case_active(T, case.id, False) is True
    archived = await store.get_eval_case(T, case.id)
    assert archived is not None and archived.is_active is False

    await store.upsert_eval_case(
        EvalCase(
            id=case.id,
            tenant_id=T,
            target_kind="workflow",
            target_ref="review-v2",
            input={"task": "review again"},
            assertions={"must_call": ["record.read"]},
            labels=["edited"],
        )
    )
    edited = await store.get_eval_case(T, case.id)
    assert edited is not None
    assert edited.target_kind == "workflow"
    assert edited.target_ref == "review-v2"
    assert edited.is_active is False
    assert [run.id for run in await store.list_eval_runs(T, case.id)] == [historical.id]
    assert [(item.id, item.is_active) for item in await store.list_eval_cases(T)] == [
        (case.id, False)
    ]

    assert await store.set_eval_case_active(T, case.id, True) is True
    restored = await store.get_eval_case(T, case.id)
    assert restored is not None and restored.is_active is True


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


# --- whole-chain verification pages ascending (SEC-168) ---------------------
async def _write_audit_chain(store, n: int):
    """A REAL hash-chained audit trail of n rows, via the production writer."""
    from boltrig.kernel.audit import AuditWriter

    writer = AuditWriter(store)
    for i in range(n):
        await writer.write(
            AuditEvent(
                tenant_id=T,
                run_id=f"r{i}",
                actor="t",
                actor_tier="human",
                action_type=ActionType.TOOL_CALL,
                noun="ticket",
                verb="ticket.create",
                status="ok",
                detail={},
                ts=None,
            )
        )
    return writer


async def _tamper_audit_row(store, seq: int) -> None:
    pool = getattr(store, "_pool", None)
    if pool is not None:
        await pool.execute(
            "UPDATE audit_log SET status='tampered' WHERE tenant_id=$1 AND seq=$2", T, seq
        )
    else:
        next(e for e in store._audit[T] if e.seq == seq).status = "tampered"


@pytest.mark.store
@pytest.mark.invariant("SEC-168")
async def test_audit_verify_walks_every_page_of_a_long_chain(store):
    # 25 rows at page_size=8 is four ascending pages: an untampered chain must
    # verify OK across every page boundary on BOTH stores (a tail window would
    # false-positive the moment the chain outgrew a single read).
    writer = await _write_audit_chain(store, 25)
    assert await writer.verify(T, page_size=8) == (True, None)


@pytest.mark.store
@pytest.mark.invariant("SEC-168")
async def test_audit_tamper_in_the_oldest_page_is_caught(store):
    # seq 2 sits in the OLDEST page: a tail window would never re-derive it.
    writer = await _write_audit_chain(store, 25)
    await _tamper_audit_row(store, 2)
    assert await writer.verify(T, page_size=8) == (False, 2)


@pytest.mark.store
@pytest.mark.invariant("SEC-168")
async def test_audit_scan_pages_ascending_and_query_keeps_tail(store):
    await _write_audit_chain(store, 5)
    # the scan seam: rows with seq > after_seq, oldest first, up to limit.
    assert [e.seq for e in await store.audit_scan(T, 0, 2)] == [1, 2]
    assert [e.seq for e in await store.audit_scan(T, 2, 10)] == [3, 4, 5]
    assert await store.audit_scan(T, 5, 10) == []
    # the existing query seam still returns the TAIL its callers rely on.
    assert [e.seq for e in await store.audit_query(T, limit=2)] == [4, 5]


@pytest.mark.store
@pytest.mark.invariant("SEC-168")
async def test_security_verify_and_scan_page_the_whole_chain(store):
    from boltrig.kernel.security_events import SecurityWriter
    from boltrig.models import SecurityEvent, SecurityEventType

    writer = SecurityWriter(store)
    for i in range(25):
        await writer.write(
            SecurityEvent(
                tenant_id=T,
                ts=utcnow(),
                event_type=SecurityEventType.LOGIN_FAILURE,
                reason=f"attempt-{i}",
                actor="eve",
            )
        )
    assert await writer.verify(T, page_size=8) == (True, None)
    assert [e.seq for e in await store.security_scan(T, 23, 10)] == [24, 25]
    assert [e.seq for e in await store.security_query(T, limit=2)] == [24, 25]
    # tampering the OLDEST page is caught on both stores.
    pool = getattr(store, "_pool", None)
    if pool is not None:
        await pool.execute(
            "UPDATE security_log SET reason='tampered' WHERE tenant_id=$1 AND seq=$2", T, 2
        )
    else:
        next(e for e in store._security[T] if e.seq == 2).reason = "tampered"
    assert await writer.verify(T, page_size=8) == (False, 2)


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
        workspace_id="ws-1",
        department_scope=["engineering", "security"],
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
@pytest.mark.invariant("SEC-141")
async def test_hitl_request_binding_round_trips(store):
    expected = _pending_hitl("req-bound")
    await store.create_hitl_request(expected)
    actual = await store.get_hitl_request(T, expected.id)
    assert actual.requested_on_behalf_of == "owner"
    assert actual.request_fingerprint == "delete-fingerprint"
    assert actual.workspace_id == "ws-1"
    assert actual.department_scope == ["engineering", "security"]


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
@pytest.mark.invariant("SEC-WRK-36")
async def test_memory_projection_status_upserts_and_filters_on_both_stores(store):
    base = utcnow()
    row = MemoryProjectionStatus(
        id="mem0:remember:f1",
        tenant_id=T,
        projection_id="mem0",
        operation="remember",
        status="pending",
        fact_id="f1",
        enqueue_attempts=1,
        operation_attempts=1,
        max_operation_attempts=3,
        first_attempt_at=base,
        last_attempt_at=base,
        last_failure_at=base,
        failure_code="projection_operation_failed",
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
    assert rows[0].enqueue_attempts == 1
    assert rows[0].operation_attempts == 1
    assert rows[0].max_operation_attempts == 3
    assert rows[0].first_attempt_at == base
    assert rows[0].last_attempt_at == base
    assert rows[0].last_failure_at == base
    assert rows[0].failure_code == "projection_operation_failed"
    assert rows[0].created_at == base
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


# --- scoped observability audit reads (SEC-69 bounding, memory/PG parity) ----
def _wi(
    item_id: str,
    *,
    workspace_id: str | None = None,
    owner: str = "engineering",
    hatchet_run_id: str | None = None,
) -> WorkItem:
    return WorkItem(
        id=item_id,
        tenant_id=T,
        source="internal",
        intent=f"intent-{item_id}",
        confidence=1.0,
        convergent=True,
        owner_member=owner,
        hatchet_run_id=hatchet_run_id,
        workspace_id=workspace_id,
    )


def _scoped_event(seq: int, run_id: str | None, *, parent=None, workspace=None) -> AuditEvent:
    e = _event(seq, f"h{seq - 1}" if seq > 1 else None)
    e.run_id = run_id
    e.parent_run_id = parent
    e.workspace_id = workspace
    return e


async def _seed_scoped_audit(store) -> None:
    for item in (
        _wi("run-org"),
        _wi("work-ws1", workspace_id="ws-1", hatchet_run_id="run-ws1"),
        _wi("work-ws2", workspace_id="ws-2", hatchet_run_id="run-ws2"),
        _wi("run-collision", workspace_id="ws-2"),
        _wi("visible-alias", workspace_id="ws-1", hatchet_run_id="run-collision"),
        _wi("run-sales", owner="sales"),
    ):
        await store.create_work_item(item)
    events = (
        _scoped_event(1, "run-org"),
        _scoped_event(2, "run-ws1", parent="run-org"),
        # the raw id of an item WITH a hatchet run id is not a run ref at all
        _scoped_event(3, "work-ws1"),
        _scoped_event(4, "run-ws2"),
        # one ref owned by BOTH a hidden and a visible item: hidden wins
        _scoped_event(5, "run-collision"),
        _scoped_event(6, "run-audit-only"),
        _scoped_event(7, "run-sales"),
        # parent folding only matters under match_parent=True
        _scoped_event(8, "child-run", parent="run-ws1"),
        _scoped_event(9, "audit-only-2", parent="run-ws2"),
        _scoped_event(10, "run-org", workspace="ws-1"),
        _scoped_event(11, "run-org", workspace="ws-2"),
    )
    for e in events:
        await store.audit_append(e)


@pytest.mark.store
@pytest.mark.invariant("SEC-69")
async def test_audit_query_scoped_pushes_run_scope_into_the_store(store):
    await _seed_scoped_audit(store)

    # Unrestricted caller in ws-1: org-wide + ws-1 event rows, minus events whose
    # run ref is owned by a hidden item (ws-2 work, or the colliding alias).
    rows = await store.audit_query_scoped(T, workspace_id="ws-1")
    assert [e.seq for e in rows] == [1, 2, 3, 6, 7, 8, 9, 10]
    # match_parent=True folds parent_run_id into the refs: seq 9's parent is
    # owned by a hidden ws-2 item, so the hidden ref now denies the event.
    rows_parent = await store.audit_query_scoped(T, workspace_id="ws-1", match_parent=True)
    assert [e.seq for e in rows_parent] == [1, 2, 3, 6, 7, 8, 10]
    # No active workspace: org-wide rows only, and ws-bound work runs are hidden.
    rows_org = await store.audit_query_scoped(T, workspace_id=None, match_parent=True)
    assert [e.seq for e in rows_org] == [1, 3, 6, 7]

    # Department-scoped caller: an event needs a ref owned by a VISIBLE item in
    # its departments; audit-only runs and other departments stay invisible.
    rows_eng = await store.audit_query_scoped(
        T, departments=["engineering"], workspace_id="ws-1", match_parent=True
    )
    assert [e.seq for e in rows_eng] == [1, 2, 8, 10]
    rows_eng_np = await store.audit_query_scoped(
        T, departments=["engineering"], workspace_id="ws-1", match_parent=False
    )
    assert [e.seq for e in rows_eng_np] == [1, 2, 10]
    rows_wide = await store.audit_query_scoped(
        T, departments=["engineering", "sales"], workspace_id="ws-1", match_parent=True
    )
    assert [e.seq for e in rows_wide] == [1, 2, 7, 8, 10]
    # An empty department scope is fail-closed.
    assert await store.audit_query_scoped(T, departments=[], workspace_id="ws-1") == []

    # run_id filter composes with the scope (and matches parent_run_id, like
    # audit_query), the tail limit keeps the NEWEST rows in ascending order.
    rows_run = await store.audit_query_scoped(T, workspace_id="ws-1", run_id="run-org")
    assert [e.seq for e in rows_run] == [1, 2, 10]
    rows_tail = await store.audit_query_scoped(T, workspace_id="ws-1", limit=3)
    assert [e.seq for e in rows_tail] == [8, 9, 10]


@pytest.mark.store
@pytest.mark.invariant("SEC-69")
async def test_audit_query_scoped_page_is_clamped(store):
    from boltrig.store.base import MAX_OBSERVABILITY_PAGE

    # A tenant past the page ceiling is never fully loaded: the read returns the
    # NEWEST clamped page in ascending order, on both backends.
    for seq in range(1, MAX_OBSERVABILITY_PAGE + 6):
        await store.audit_append(_scoped_event(seq, f"r{seq}"))
    rows = await store.audit_query_scoped(T, limit=MAX_OBSERVABILITY_PAGE + 500)
    assert len(rows) == MAX_OBSERVABILITY_PAGE
    assert [e.seq for e in rows] == list(range(6, MAX_OBSERVABILITY_PAGE + 6))


@pytest.mark.store
@pytest.mark.invariant("SEC-ACCOUNT-AUDIT-PAGE-01")
async def test_account_activity_filters_before_offset_page_on_both_stores(store):
    for seq, actor, behalf in (
        (1, "alice", None),
        (2, "delegate", "alice"),
        (3, "alice", None),
        *((seq, "other", None) for seq in range(4, 14)),
    ):
        event = _event(seq, f"h{seq - 1}" if seq > 1 else None)
        event.actor = actor
        event.on_behalf_of = behalf
        await store.audit_append(event)

    first, next_offset = await store.account_activity_page(T, "alice", limit=2, offset=0)
    second, end = await store.account_activity_page(T, "alice", limit=2, offset=2)
    assert [e.seq for e in first] == [3, 2]
    assert next_offset == 2
    assert [e.seq for e in second] == [1]
    assert end is None


@pytest.mark.store
@pytest.mark.invariant("SEC-ACCOUNT-AUDIT-PAGE-01")
async def test_audit_and_security_search_filter_before_pages_on_both_stores(store):
    for seq in range(1, 7):
        event = _event(seq, f"h{seq - 1}" if seq > 1 else None)
        event.actor = "alice" if seq in {1, 3, 5} else "other"
        event.resource = "ticket" if seq != 3 else "invoice"
        await store.audit_append(event)

    audit_page, audit_next = await store.audit_search_page(
        T, actor="alice", resource="ticket", limit=1
    )
    audit_end, audit_done = await store.audit_search_page(
        T, actor="alice", resource="ticket", limit=1, offset=1
    )
    assert [e.seq for e in audit_page] == [5] and audit_next == 1
    assert [e.seq for e in audit_end] == [1] and audit_done is None

    for seq in range(1, 5):
        await store.security_append(
            SecurityEvent(
                tenant_id=T,
                seq=seq,
                ts=utcnow(),
                event_type=SecurityEventType.LOGIN_FAILURE,
                reason="test",
                actor="alice" if seq % 2 else "other",
                prev_hash=f"s{seq - 1}" if seq > 1 else None,
                hash=f"s{seq}",
            )
        )
    security_page, security_next = await store.security_search_page(T, actor="alice", limit=1)
    security_end, security_done = await store.security_search_page(
        T, actor="alice", limit=1, offset=1
    )
    assert [e.seq for e in security_page] == [3] and security_next == 1
    assert [e.seq for e in security_end] == [1] and security_done is None


@pytest.mark.store
@pytest.mark.invariant("SEC-69")
async def test_audit_literal_query_matches_structural_fields_on_both_stores(store):
    target = _event(1, None)
    target.actor = "CaseKeeper"
    target.verb = "Approval.Run"
    target.status = "needs_review"
    target.run_id = "RUN-ABC"
    target.parent_run_id = "PARENT-XYZ"
    target.resource = "Invoice"
    target.resource_id = r"Case%_\42"
    target.detail = {"secret_note": "not-a-search-column"}
    decoy = _event(2, "h1")
    decoy.resource_id = "CaseABZ42"
    await store.audit_append(target)
    await store.audit_append(decoy)

    for query in (
        "casekeeper",
        "approval.run",
        "needs_review",
        "run-abc",
        "parent-xyz",
        "invoice",
        r"case%_\42",
        "%_\\",
    ):
        rows, next_offset = await store.audit_search_page(T, query=query, limit=1)
        assert [row.seq for row in rows] == [1]
        assert next_offset is None
    rows, _ = await store.audit_search_page(T, query="not-a-search-column", limit=10)
    assert rows == []


@pytest.mark.store
@pytest.mark.invariant("SEC-69")
async def test_list_work_items_by_refs_matches_ids_and_hatchet_aliases(store):
    await store.create_work_item(_wi("i-1", hatchet_run_id="h-1"))
    await store.create_work_item(_wi("i-2"))
    other = _wi("i-3")
    other.tenant_id = "rival"
    await store.create_work_item(other)

    rows = await store.list_work_items_by_refs(T, ["i-1", "h-1", "i-2", "i-3", "nope"])
    assert [w.id for w in rows] == ["i-1", "i-2"]
    assert await store.list_work_items_by_refs(T, []) == []


@pytest.mark.store
@pytest.mark.invariant("SEC-69")
async def test_list_run_items_scoped_pushes_run_scope_into_the_store(store):
    await _seed_scoped_audit(store)

    # ws-1 caller: org-wide + ws-1 items, minus any whose run ref is also owned
    # by a hidden item (visible-alias carries run-collision, which a hidden ws-2
    # item owns - hidden wins, exactly the old RunScope.permits rule).
    rows = await store.list_run_items_scoped(T, workspace_id="ws-1")
    assert [w.id for w in rows] == ["run-org", "run-sales", "work-ws1"]
    # No active workspace: org-wide items only.
    rows_org = await store.list_run_items_scoped(T, workspace_id=None)
    assert [w.id for w in rows_org] == ["run-org", "run-sales"]
    # A department scope narrows to its own visible items; empty is fail-closed.
    rows_eng = await store.list_run_items_scoped(
        T, departments=["engineering"], workspace_id="ws-1"
    )
    assert [w.id for w in rows_eng] == ["run-org", "work-ws1"]
    assert await store.list_run_items_scoped(T, departments=[], workspace_id="ws-1") == []

    # Keyset pages walk the scoped slice in id order with no overlap.
    page1 = await store.list_run_items_scoped(T, workspace_id="ws-1", limit=2)
    assert [w.id for w in page1] == ["run-org", "run-sales"]
    page2 = await store.list_run_items_scoped(T, workspace_id="ws-1", limit=2, cursor=page1[-1].id)
    assert [w.id for w in page2] == ["work-ws1"]


@pytest.mark.store
@pytest.mark.invariant("SEC-69")
async def test_execution_search_scope_and_text_match_on_both_stores(store):
    target = WorkItem(
        id=r"exec%_\visible",
        tenant_id=T,
        workspace_id="ws-1",
        source="linear-source",
        source_id=r"case%_\42",
        intent="Quarterly Renewal Plan",
        confidence=1.0,
        convergent=True,
        status=WorkStatus.FAILED,
        owner_member="engineering",
        hatchet_run_id="run-renewal-42",
        on_behalf_of="alice-search",
    )
    for item in (
        target,
        _wi(
            "collision-hidden",
            workspace_id="ws-2",
            owner="engineering",
            hatchet_run_id="run-collision",
        ),
        _wi(
            "collision-visible",
            workspace_id="ws-1",
            owner="engineering",
            hatchet_run_id="run-collision",
        ),
    ):
        await store.create_work_item(item)
    collision = await store.get_work_item(T, "collision-visible")
    collision.intent = "resurrect-me"
    await store.update_work_item(collision)
    rival = replace(target, id="rival-match", tenant_id="rival")
    await store.create_work_item(rival)

    for query in (
        "quarterly renewal",
        r"exec%_\visible",
        "RUN-RENEWAL-42",
        "engineering",
        "ALICE-SEARCH",
        "LINEAR-SOURCE",
        r"case%_\42",
        "FAILED",
        "%_\\",
    ):
        rows = await store.search_execution_items_scoped(
            T,
            query,
            departments=["engineering"],
            workspace_id="ws-1",
            limit=1,
        )
        assert [row.id for row in rows] == [target.id]
    assert (
        await store.search_execution_items_scoped(
            T,
            "resurrect-me",
            departments=["engineering"],
            workspace_id="ws-1",
            limit=10,
        )
        == []
    )


# --- adapter lifecycle deletes (SEC-22) --------------------------------------
@pytest.mark.store
@pytest.mark.invariant("SEC-22")
async def test_adapter_lifecycle_deletes_are_idempotent_and_tenant_scoped(store):
    from boltrig.models import (
        AdapterRecord,
        Noun,
        TargetType,
        Verb,
        VerbBinding,
    )

    for tenant in (T, "rival"):
        await store.upsert_noun(Noun(id="ticket", tenant_id=tenant))
        await store.upsert_verb(
            Verb(
                id="ticket.read",
                tenant_id=tenant,
                noun_id="ticket",
                input_schema={},
                output_schema={},
            )
        )
        await store.upsert_binding(
            VerbBinding(
                verb_id="ticket.read",
                tenant_id=tenant,
                target_type=TargetType.ADAPTER,
                target_ref="ext-mcp",
            )
        )
        await store.upsert_adapter(
            AdapterRecord(
                id="ext-mcp",
                tenant_id=tenant,
                version="1",
                runtime="mcp",
                source="manual",
                module_ref="m",
            )
        )
        await store.set_credential_ref(
            tenant, "ext-mcp-mcp-token", {"store": "env", "ref": "TOK", "kind": "api_key"}
        )

    # the governed delete path's store primitives remove one tenant's rows...
    await store.delete_binding(T, "ticket.read")
    await store.delete_verb(T, "ticket.read")
    await store.delete_noun(T, "ticket")
    await store.delete_adapter(T, "ext-mcp")
    await store.delete_credential_ref(T, "ext-mcp-mcp-token")
    assert await store.get_binding(T, "ticket.read") is None
    assert await store.get_verb(T, "ticket.read") is None
    assert await store.get_noun(T, "ticket") is None
    assert await store.get_adapter(T, "ext-mcp") is None
    assert await store.get_credential_ref(T, "ext-mcp-mcp-token") is None

    # ...are idempotent no-ops on absent rows...
    await store.delete_binding(T, "ticket.read")
    await store.delete_verb(T, "ticket.read")
    await store.delete_noun(T, "ticket")
    await store.delete_adapter(T, "ext-mcp")
    await store.delete_credential_ref(T, "ext-mcp-mcp-token")

    # ...and never touch another tenant (SEC-08).
    assert await store.get_binding("rival", "ticket.read") is not None
    assert await store.get_verb("rival", "ticket.read") is not None
    assert await store.get_noun("rival", "ticket") is not None
    assert await store.get_adapter("rival", "ext-mcp") is not None
    assert (await store.get_credential_ref("rival", "ext-mcp-mcp-token")) is not None


# --- the work-item lease fence (D1/D6/D7) -----------------------------------
# [2026] VJS-CC-BOLTRIG-WORK-ITEM-LEASE-FENCE-001. Nothing renews a work-item
# lease, so a step that outruns lease_seconds is handed to a SECOND executor while
# the first still runs. Every pump write was an unconditional full-row upsert with
# no owner and no status predicate, so the loser overwrote the winner's terminal
# record and rolled `attempts` back.
#
# The fence has to be evaluated by the backend, in the same statement as the
# update, against the tuple minted AT CLAIM. A read-then-write check in the caller
# cannot decide a read-then-write race: that shape was authored, and a reviewer
# applied it and reproduced the original defect.


async def _leased_item(store, item_id: str = "w-lease"):
    await store.create_work_item(
        WorkItem(
            id=item_id,
            tenant_id=T,
            source="internal",
            intent="long step",
            confidence=1.0,
            convergent=True,
            status=WorkStatus.PENDING,
            owner_member="engineering",
        )
    )
    claimed = await store.claim_work_item(T, "worker-a", 300)
    assert claimed is not None and claimed.id == item_id
    return claimed


@pytest.mark.store
@pytest.mark.invariant("US-FLT-05")
async def test_a_worker_that_lost_its_lease_cannot_overwrite_the_winner(store):
    """The defect itself, on both backends. Body A claims, its lease expires, body
    B reclaims and settles; A's late write must be REFUSED, not applied."""
    claimed = await _leased_item(store)
    a_owner, a_expiry = claimed.lease_owner, claimed.lease_expires_at

    # The lease lapses and a rival reclaims. attempts goes 1 -> 2.
    expired = replace(claimed, lease_expires_at=utcnow() - timedelta(seconds=1))
    await store.update_work_item(expired)
    rival = await store.claim_work_item(T, "worker-b", 300)
    assert rival is not None and rival.lease_owner == "worker-b"
    assert rival.attempts == 2

    # The rival settles the item.
    await store.update_work_item(
        replace(
            rival,
            status=WorkStatus.DONE,
            result={"who": "winner"},
            lease_owner=None,
            lease_expires_at=None,
        )
    )

    # Body A, still running, now writes its stale snapshot fenced on the tuple it
    # was GIVEN at claim. It must not land.
    wrote = await store.update_work_item_if_leased(
        replace(claimed, status=WorkStatus.DONE, result={"who": "loser"}),
        lease_owner=a_owner,
        lease_expires_at=a_expiry,
    )
    assert wrote is False, "the loser's write was applied over the winner's record"

    final = await store.get_work_item(T, "w-lease")
    assert final.result == {"who": "winner"}
    assert final.status == WorkStatus.DONE
    assert final.attempts == 2, "attempts was rolled back by a stale writer"


@pytest.mark.store
@pytest.mark.invariant("US-FLT-05")
async def test_the_lease_holder_can_still_write(store):
    """The fence must not refuse the legitimate writer, which is the failure mode
    an owner-equality fence would have had on the durable lane."""
    claimed = await _leased_item(store, "w-holder")
    wrote = await store.update_work_item_if_leased(
        replace(claimed, status=WorkStatus.DONE, result={"ok": True}),
        lease_owner=claimed.lease_owner,
        lease_expires_at=claimed.lease_expires_at,
    )
    assert wrote is True
    final = await store.get_work_item(T, "w-holder")
    assert final.status == WorkStatus.DONE and final.result == {"ok": True}


@pytest.mark.store
@pytest.mark.invariant("US-FLT-05")
async def test_a_read_does_not_hand_back_the_stored_row(store):
    """D6, and the reason the fence is meaningful at all. If a read returns the
    LIVE row, the caller's object IS the stored object, every comparison trivially
    agrees, and the fence above would pass while fencing nothing. Postgres has
    always copied; the memory store did not, and that divergence was the real
    obstacle the case file mis-described as 'InMemoryStore cannot express it'."""
    await _leased_item(store, "w-detach")
    first = await store.get_work_item(T, "w-detach")
    first.result = {"mutated": "without a write call"}

    second = await store.get_work_item(T, "w-detach")
    assert second.result != {"mutated": "without a write call"}, (
        "the store handed back its live row: a caller mutated it with no write"
    )


# --- decision-0021 realtime call metadata -----------------------------------
@pytest.mark.store
@pytest.mark.invariant("SEC-WRK-03")
@pytest.mark.invariant("SEC-WRK-04")
@pytest.mark.invariant("SEC-08")
async def test_realtime_call_media_claim_and_events_match_on_both_stores(store):
    from datetime import timedelta

    await store.create_conversation(Conversation(id="conv-call", tenant_id=T, user_id="alice"))
    await store.upsert_channel(
        Channel(
            id="ch-call",
            tenant_id=T,
            platform="voice",
            name="Voice",
            transport="socket",
        )
    )
    call = RealtimeCallSession(
        id="call-1",
        tenant_id=T,
        conversation_id="conv-call",
        owner_id="alice",
        channel_id="ch-call",
        status="creating",
        media_token_hash="token-digest",
        media_token_expires_at=utcnow() + timedelta(minutes=1),
        tool_context={"allow": ["ticket.create"], "deny": []},
    )
    await store.create_realtime_call(call)
    assert await store.get_realtime_call("rival", call.id) is None
    assert (
        await store.claim_realtime_call_media(T, call.id, ["wrong-channel"], "token-digest") is None
    )
    claimed = await store.claim_realtime_call_media(T, call.id, ["ch-call"], "token-digest")
    assert claimed is not None and claimed.status == "active"
    assert claimed.media_token_hash is None
    assert await store.claim_realtime_call_media(T, call.id, ["ch-call"], "token-digest") is None

    event = RealtimeCallEvent(
        id="event-1",
        tenant_id=T,
        call_id=call.id,
        type="transcript",
        participant_id="user",
        payload={"text": "hello", "final": True},
    )
    await store.append_realtime_call_event(event)
    await store.append_realtime_call_event(event)
    assert await store.list_realtime_call_events("rival", call.id) == []
    events = await store.list_realtime_call_events(T, call.id)
    assert [(row.id, row.payload) for row in events] == [
        ("event-1", {"text": "hello", "final": True})
    ]
    hitl = RealtimeCallEvent(
        id="event-hitl",
        tenant_id=T,
        call_id=call.id,
        type="hitl",
        payload={"request_id": "req-call", "status": "ok"},
    )
    usage = RealtimeCallEvent(
        id="event-usage",
        tenant_id=T,
        call_id=call.id,
        type="usage",
        payload={
            "input_audio_bytes": 100,
            "output_audio_bytes": 50,
            "tool_calls": 1,
            "provider_input_tokens": 12,
            "provider_output_tokens": 8,
            "estimated_cost_micros": 7,
            "pricing_revision": "contract-v1",
            "cost_status": "estimated",
        },
    )
    await store.append_realtime_call_event(hitl)
    await store.append_realtime_call_event(usage)
    found = await store.get_realtime_call_hitl_event(T, call.id, "req-call")
    assert found is not None and found.payload["status"] == "ok"
    assert await store.get_realtime_call_hitl_event("rival", call.id, "req-call") is None
    assert await store.summarize_realtime_call_usage(T, call.id) == {
        "input_audio_bytes": 100,
        "output_audio_bytes": 50,
        "tool_calls": 1,
        "provider_input_tokens": 12,
        "provider_output_tokens": 8,
        "estimated_cost_micros": 7,
        "pricing_revision": "contract-v1",
        "cost_status": "estimated",
    }


@pytest.mark.store
@pytest.mark.invariant("SEC-WRK-06")
@pytest.mark.invariant("SEC-08")
async def test_integration_catalogue_and_connection_state_match_on_both_stores(store):
    from boltrig.models.integrations import (
        IntegrationCatalogueRecord,
        IntegrationConnection,
    )
    from boltrig.models.integration_auth import (
        IntegrationSecretContract,
        IntegrationSecretField,
    )

    item = IntegrationCatalogueRecord(
        id="github",
        tenant_id=T,
        label="GitHub",
        category="work",
        transport="rest",
        auth=["oauth2", "manual_secret"],
        description="Reviewed source control connector.",
        certification="certified",
        adapter_id="github-adapter",
        secret_contract=IntegrationSecretContract(
            version="github_v1",
            credential_kind="token",
            fields=(
                IntegrationSecretField(
                    name="token",
                    label="Personal access token",
                    max_length=200,
                ),
            ),
        ),
    )
    await store.upsert_integration_catalogue(item)
    item.auth.append("channel_pairing")
    assert await store.get_integration_catalogue("rival", item.id) is None
    catalogue = await store.list_integration_catalogue(T)
    assert [row.id for row in catalogue] == ["github"]
    assert catalogue[0].auth == ["oauth2", "manual_secret"]
    assert catalogue[0].secret_contract is not item.secret_contract
    assert catalogue[0].secret_contract is not None
    assert catalogue[0].secret_contract.version == "github_v1"
    catalogue[0].auth.append("channel_pairing")
    stored_item = await store.get_integration_catalogue(T, item.id)
    assert stored_item is not None
    assert stored_item.auth == ["oauth2", "manual_secret"]
    assert stored_item.secret_contract is not None
    connection = IntegrationConnection(
        id="conn-github",
        tenant_id=T,
        integration_id=item.id,
        adapter_id="github-adapter",
        label="Engineering",
        health="ok",
        credential_ref="cred-github",
        credential_owned=True,
    )
    assert await store.create_integration_connection(connection)
    assert not await store.create_integration_connection(
        replace(connection, id="conn-github-duplicate")
    )
    connection.accounts.append({"id": "caller-only"})
    assert await store.get_integration_connection("rival", connection.id) is None
    connections = await store.list_integration_connections(T)
    assert [row.id for row in connections] == ["conn-github"]
    assert connections[0].accounts == []
    connections[0].accounts.append({"id": "reader-only"})
    stored_connection = await store.get_integration_connection(T, connection.id)
    assert stored_connection is not None and stored_connection.accounts == []
    revoked = await store.revoke_integration_connection(T, connection.id)
    assert revoked is not None
    assert revoked.health == "revoked" and revoked.credential_ref is None
    assert await store.revoke_integration_connection(T, connection.id) is None
    assert await store.create_integration_connection(
        replace(connection, id="conn-github-replacement")
    )


@pytest.mark.store
@pytest.mark.invariant("SEC-WRK-06")
@pytest.mark.invariant("SEC-08")
async def test_integration_health_update_cannot_resurrect_a_revoked_connection(store):
    from boltrig.models.integrations import (
        IntegrationCatalogueRecord,
        IntegrationConnection,
    )

    await store.upsert_integration_catalogue(
        IntegrationCatalogueRecord(
            id="github",
            tenant_id=T,
            label="GitHub",
            category="work",
            transport="rest",
            auth=["manual_secret"],
            description="Health/revoke race fixture.",
            certification="certified",
            adapter_id="github-adapter",
        )
    )

    connection = IntegrationConnection(
        id="conn-health-revoke-race",
        tenant_id=T,
        integration_id="github",
        adapter_id="github-adapter",
        label="Engineering",
        health="pending",
        credential_ref="cred-health-revoke-race",
        credential_owned=True,
    )
    assert await store.create_integration_connection(connection)

    first_check = utcnow()
    checked = await store.update_integration_connection_health_if_active(
        T, connection.id, "ok", first_check
    )
    assert checked is not None
    assert checked.health == "ok"
    assert checked.credential_ref == connection.credential_ref
    assert checked.last_checked_at == first_check

    revoked = await store.revoke_integration_connection(T, connection.id)
    assert revoked is not None and revoked.health == "revoked"
    assert revoked.credential_ref is None

    stale_check = await store.update_integration_connection_health_if_active(
        T, connection.id, "degraded", utcnow()
    )
    assert stale_check is None
    stored = await store.get_integration_connection(T, connection.id)
    assert stored is not None
    assert stored.health == "revoked"
    assert stored.credential_ref is None


@pytest.mark.store
@pytest.mark.invariant("SEC-WRK-06")
@pytest.mark.invariant("SEC-140")
async def test_atomic_integration_credential_lifecycle_matches_on_both_stores(store):
    from boltrig.kernel.credentials import CredentialResolver
    from boltrig.kernel.integration_credentials import integration_manual_secret_ref
    from boltrig.models.integrations import (
        IntegrationCatalogueRecord,
        IntegrationConnection,
    )

    await store.upsert_integration_catalogue(
        IntegrationCatalogueRecord(
            id="durable-tickets",
            tenant_id=T,
            label="Durable tickets",
            category="work",
            transport="rest",
            auth=["manual_secret"],
            description="Atomic integration fixture.",
            certification="certified",
            adapter_id="durable-tickets-adapter",
        )
    )
    credential = integration_manual_secret_ref(
        "durable-tickets",
        "durable-tickets-adapter",
        "api_key",
        "tickets_v1",
        {"opaque": "replica-visible-secret"},
    )
    connection = IntegrationConnection(
        id="conn-durable-tickets",
        tenant_id=T,
        integration_id="durable-tickets",
        adapter_id="durable-tickets-adapter",
        label="Durable tickets",
        credential_ref="cred-durable-tickets",
        credential_owned=True,
    )

    assert await store.create_integration_connection_with_credential(connection, credential)
    active = await store.get_active_integration_connection_for_adapter(T, connection.adapter_id)
    assert active is not None and active.id == connection.id
    # Two fresh resolvers model a restart and a second replica. Neither receives
    # a process-local bind; the durable active connection is their authority.
    for resolver in (CredentialResolver(store), CredentialResolver(store)):
        resolved = await resolver.resolve_for_adapter(T, connection.adapter_id)
        assert resolved is not None
        assert resolved.material == {"opaque": "replica-visible-secret"}

    duplicate = replace(
        connection,
        id="conn-durable-tickets-duplicate",
        credential_ref="cred-durable-tickets-duplicate",
    )
    assert not await store.create_integration_connection_with_credential(duplicate, credential)
    assert not await store.has_credential_ref(T, duplicate.credential_ref)

    revoked, detached_ref, deleted = await store.revoke_integration_connection_with_credential(
        T, connection.id
    )
    assert revoked is not None and revoked.health == "revoked"
    assert detached_ref == connection.credential_ref and deleted
    assert not await store.has_credential_ref(T, connection.credential_ref)
    assert await CredentialResolver(store).resolve_for_adapter(T, connection.adapter_id) is None


@pytest.mark.store
@pytest.mark.invariant("SEC-WRK-19")
async def test_authored_definition_lifecycle_matches_on_both_stores(store):
    noun = Noun(
        id="invoice",
        tenant_id=T,
        description="Invoice",
        schema={"type": "object"},
    )
    verb = Verb(
        id="invoice.read",
        tenant_id=T,
        noun_id=noun.id,
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        description="Read an invoice",
    )
    binding = VerbBinding(
        verb_id=verb.id,
        tenant_id=T,
        target_type=TargetType.ADAPTER,
        target_ref="billing",
    )
    skill = Skill(
        id="billing/review",
        tenant_id=T,
        version="1.0.0",
        prompt_fragment="Review the invoice.",
        tool_grants=[verb.id],
    )
    await store.upsert_noun(noun)
    await store.upsert_verb(verb)
    await store.upsert_binding(binding)
    await store.upsert_skill(skill)

    assert await store.set_noun_active(T, noun.id, False) is not None
    assert await store.set_verb_active(T, verb.id, False) is not None
    assert await store.set_skill_active(T, skill.id, False) is not None
    assert await store.get_noun(T, noun.id) is None
    assert await store.get_verb(T, verb.id) is None
    assert await store.get_skill(T, skill.id) is None
    assert await store.list_nouns(T) == []
    assert await store.list_verbs(T) == []
    assert await store.list_skills(T) == []
    assert (await store.get_noun_any(T, noun.id)).is_active is False
    assert (await store.get_verb_any(T, verb.id)).is_active is False
    assert (await store.get_skill_any(T, skill.id)).is_active is False
    assert [row.id for row in await store.list_all_nouns(T)] == [noun.id]
    assert [row.id for row in await store.list_all_verbs(T)] == [verb.id]
    assert [row.id for row in await store.list_all_skills(T)] == [skill.id]
    assert await store.get_binding(T, verb.id) == binding

    # Ordinary replacement upserts cannot accidentally reactivate a withdrawn
    # definition. A new skill version inherits the current lifecycle status.
    await store.upsert_noun(replace(noun, description="Updated invoice", is_active=True))
    await store.upsert_verb(replace(verb, description="Updated reader", is_active=True))
    await store.upsert_skill(
        replace(
            skill,
            version="1.1.0",
            prompt_fragment="Review the updated invoice.",
            is_active=True,
        )
    )
    assert (await store.get_noun_any(T, noun.id)).is_active is False
    assert (await store.get_verb_any(T, verb.id)).is_active is False
    latest_skill = await store.get_skill_any(T, skill.id)
    assert latest_skill.version == "1.1.0" and latest_skill.is_active is False
    assert await store.get_binding(T, verb.id) == binding

    assert await store.set_noun_active(T, noun.id, True) is not None
    assert await store.set_verb_active(T, verb.id, True) is not None
    assert await store.set_skill_active(T, skill.id, True) is not None
    assert (await store.get_noun(T, noun.id)).description == "Updated invoice"
    assert (await store.get_verb(T, verb.id)).description == "Updated reader"
    assert (await store.get_skill(T, skill.id)).version == "1.1.0"
    assert await store.get_binding(T, verb.id) == binding
