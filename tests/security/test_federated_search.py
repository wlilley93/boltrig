"""Federated search preserves every source's canonical visibility fence."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    ActionType,
    AuditEvent,
    Conversation,
    ConversationMessage,
    ConversationStatus,
    DegradedMode,
    GrantMissing,
    MessageRole,
    WorkItem,
    WorkStatus,
    utcnow,
)
from boltrig.store import InMemoryStore

T = "search-tenant"
HEADERS = {
    "x-boltrig-tenant": T,
    "x-boltrig-subject": "alice",
    "x-boltrig-role": "member",
    "x-boltrig-tier": "human",
    "x-boltrig-departments": "engineering",
    "x-boltrig-workspace": "workspace-a",
}


async def _conversation(
    store,
    *,
    tenant: str,
    conversation_id: str,
    owner: str,
    content: str,
) -> None:
    await store.create_conversation(
        Conversation(
            id=conversation_id,
            tenant_id=tenant,
            user_id=owner,
            title="Private thread",
            status=ConversationStatus.ACTIVE,
        )
    )
    await store.add_message(
        ConversationMessage(
            id=f"message-{conversation_id}",
            conversation_id=conversation_id,
            tenant_id=tenant,
            role=MessageRole.USER,
            content=content,
        )
    )


async def _work(
    store,
    *,
    tenant: str,
    item_id: str,
    run_id: str,
    department: str,
    workspace: str,
    intent: str,
) -> None:
    await store.create_work_item(
        WorkItem(
            id=item_id,
            tenant_id=tenant,
            source="internal",
            intent=intent,
            confidence=1.0,
            convergent=True,
            status=WorkStatus.IN_FLIGHT,
            owner_member=department,
            hatchet_run_id=run_id,
            workspace_id=workspace,
            on_behalf_of="alice",
        )
    )


async def _scoped_kernel() -> Kernel:
    store = InMemoryStore()
    kernel = Kernel(store)
    await _conversation(
        store,
        tenant=T,
        conversation_id="conversation-visible",
        owner="alice",
        content=f"Apollo launch notes {'x' * 400}",
    )
    await _conversation(
        store,
        tenant=T,
        conversation_id="conversation-other-user",
        owner="bob",
        content="Apollo private note from Bob",
    )
    await _conversation(
        store,
        tenant="other-tenant",
        conversation_id="conversation-other-tenant",
        owner="alice",
        content="Apollo from another tenant",
    )

    await _work(
        store,
        tenant=T,
        item_id="work-visible",
        run_id="run-visible",
        department="engineering",
        workspace="workspace-a",
        intent="Apollo visible execution",
    )
    await _work(
        store,
        tenant=T,
        item_id="work-wrong-department",
        run_id="run-wrong-department",
        department="legal",
        workspace="workspace-a",
        intent="Apollo legal execution",
    )
    await _work(
        store,
        tenant=T,
        item_id="work-wrong-workspace",
        run_id="run-wrong-workspace",
        department="engineering",
        workspace="workspace-b",
        intent="Apollo other workspace execution",
    )
    await _work(
        store,
        tenant="other-tenant",
        item_id="work-other-tenant",
        run_id="run-other-tenant",
        department="engineering",
        workspace="workspace-a",
        intent="Apollo other tenant execution",
    )

    for run_id, workspace, verb in (
        ("run-visible", "workspace-a", "apollo.visible"),
        ("run-wrong-department", "workspace-a", "apollo.legal"),
        ("run-wrong-workspace", "workspace-b", "apollo.other_workspace"),
    ):
        await kernel.audit.write(
            AuditEvent(
                tenant_id=T,
                ts=utcnow(),
                actor="agent:worker",
                action_type=ActionType.TOOL_CALL,
                status="ok",
                run_id=run_id,
                verb=verb,
                workspace_id=workspace,
            )
        )
    await kernel.audit.write(
        AuditEvent(
            tenant_id="other-tenant",
            ts=utcnow(),
            actor="agent:worker",
            action_type=ActionType.TOOL_CALL,
            status="ok",
            run_id="run-other-tenant",
            verb="apollo.other_tenant",
            workspace_id="workspace-a",
        )
    )
    return kernel


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-23")
def test_federated_search_groups_sources_without_widening_scope():
    kernel = asyncio.run(_scoped_kernel())
    client = TestClient(create_app(kernel=kernel))

    response = client.post(
        "/v1/search",
        headers=HEADERS,
        json={
            "query": "Apollo",
            "limit": 5,
            "sources": ["audit", "conversations", "executions"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "Apollo"
    assert [item["source"] for item in body["sources"]] == [
        "audit",
        "conversations",
        "executions",
    ]
    assert [item["status"] for item in body["sources"]] == ["ok", "ok", "ok"]
    # Results stay grouped in REQUESTED source order; unlike items within
    # Knowledge, no score can reorder one source ahead of another.
    assert [item["source"] for item in body["results"]] == [
        "audit",
        "conversations",
        "executions",
    ]
    assert body["results"][0]["metadata"]["run_id"] == "run-visible"
    assert body["results"][1]["id"] == "conversation-visible"
    assert body["results"][2]["id"] == "run-visible"
    assert body["results"][2]["route"] == "runs"
    assert body["results"][2]["route_id"] == "run-visible"
    assert len(body["results"][1]["preview"]) <= 240
    rendered = str(body)
    for hidden in (
        "conversation-other-user",
        "conversation-other-tenant",
        "run-wrong-department",
        "run-wrong-workspace",
        "run-other-tenant",
    ):
        assert hidden not in rendered


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-23")
def test_federated_search_reports_expected_partial_failures_only():
    kernel = asyncio.run(_scoped_kernel())

    async def expected_failures(noun, verb, params, context, **kwargs):
        assert context.workspace_id == "workspace-a"
        if verb == "knowledge.search":
            assert context.extra["principal_scope"]["departments"] == ["engineering"]
            raise GrantMissing("knowledge not granted")
        if verb == "memory.recall":
            assert "user:alice" in context.extra["memory_scopes"]
            raise DegradedMode({"reason": "memory backend offline"})
        raise AssertionError(f"unexpected invocation {noun}.{verb}")

    kernel.invoke = expected_failures  # type: ignore[method-assign]
    client = TestClient(create_app(kernel=kernel))
    response = client.post(
        "/v1/search",
        headers=HEADERS,
        json={
            "query": "Apollo",
            "sources": ["knowledge", "conversations", "memory"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["results"] == [{
        "source": "conversations",
        "id": "conversation-visible",
        "title": "Private thread",
        "preview": body["results"][0]["preview"],
        "route": "chat",
        "route_id": "conversation-visible",
        "occurred_at": body["results"][0]["occurred_at"],
        "metadata": {"status": "active"},
    }]
    assert body["sources"] == [
        {
            "source": "knowledge",
            "status": "denied",
            "count": 0,
            "truncated": False,
            "reason": "grant_missing",
        },
        {
            "source": "conversations",
            "status": "ok",
            "count": 1,
            "truncated": False,
        },
        {
            "source": "memory",
            "status": "unavailable",
            "count": 0,
            "truncated": False,
            "reason": "degraded",
        },
    ]

    async def unexpected_failure(noun, verb, params, context, **kwargs):
        raise RuntimeError("programming failure")

    kernel.invoke = unexpected_failure  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="programming failure"):
        client.post(
            "/v1/search",
            headers=HEADERS,
            json={"query": "Apollo", "sources": ["knowledge"]},
        )


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-23")
def test_federated_search_keeps_source_scores_local_and_marks_truncation():
    kernel = Kernel(InMemoryStore())

    async def source_outputs(noun, verb, params, context, **kwargs):
        assert params["limit"] == 2
        if verb == "memory.recall":
            return {
                "facts": [
                    {
                        "id": "fact-a",
                        "kind": "preference",
                        "content": f"Apollo memory {'m' * 400}",
                        "owner_scope": "user:alice",
                        "data_class": "internal",
                        "provenance": {"source_kind": "conversation"},
                    },
                    {"id": "fact-b", "kind": "note", "content": "Apollo overflow"},
                ]
            }
        if verb == "knowledge.search":
            return {
                "hits": [
                    {
                        "asset_id": "asset-a",
                        "revision_id": "revision-a",
                        "segment_id": "segment-a",
                        "title": "Apollo handbook",
                        "filename": "apollo.md",
                        "text": f"Apollo knowledge {'k' * 400}",
                        "score": 0.99,
                        "citation": {"asset_id": "asset-a", "segment_id": "segment-a"},
                    },
                    {
                        "asset_id": "asset-b",
                        "segment_id": "segment-b",
                        "title": "Overflow",
                        "text": "Apollo overflow",
                        "score": 1.0,
                    },
                ]
            }
        raise AssertionError(f"unexpected invocation {noun}.{verb}")

    kernel.invoke = source_outputs  # type: ignore[method-assign]
    response = TestClient(create_app(kernel=kernel)).post(
        "/v1/search",
        headers=HEADERS,
        json={"query": "Apollo", "limit": 1, "sources": ["memory", "knowledge"]},
    )

    assert response.status_code == 200
    body = response.json()
    # Knowledge's score is meaningful only inside Knowledge. It cannot move that
    # hit ahead of the requested Memory source group.
    assert [item["source"] for item in body["results"]] == ["memory", "knowledge"]
    assert body["results"][0]["id"] == "fact-a"
    assert body["results"][0]["route_id"] == "fact-a"
    assert "score" not in body["results"][0]
    assert body["results"][1]["id"] == "segment-a"
    assert body["results"][1]["route_id"] == "asset-a"
    assert body["results"][1]["score"] == 0.99
    assert all(len(item["preview"]) <= 240 for item in body["results"])
    assert body["sources"] == [
        {
            "source": "memory",
            "status": "ok",
            "count": 1,
            "truncated": True,
        },
        {
            "source": "knowledge",
            "status": "ok",
            "count": 1,
            "truncated": True,
        },
    ]


@pytest.mark.security
@pytest.mark.parametrize(
    "body",
    [
        {"query": ""},
        {"query": "x" * 201},
        {"query": "apollo", "limit": 0},
        {"query": "apollo", "limit": 11},
        {"query": "apollo", "limit": True},
        {"query": "apollo", "sources": ["conversations", "unknown"]},
        {"query": "apollo", "sources": "conversations"},
    ],
)
def test_federated_search_rejects_out_of_contract_requests(body):
    client = TestClient(create_app(kernel=Kernel(InMemoryStore())))
    response = client.post("/v1/search", headers=HEADERS, json=body)
    assert response.status_code == 400
    assert response.json()["status"] == "error"
