"""Workspace authorization regressions for externally visible WorkItem runs."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import Principal, create_app
from boltrig.models import (
    ActionType,
    AuditEvent,
    GrantSet,
    WorkflowDefinition,
    WorkflowSource,
    WorkItem,
    WorkStatus,
    utcnow,
)
from boltrig.store import InMemoryStore

T = "acme"


def _principal(workspace_id: str | None) -> Principal:
    return Principal(
        tenant_id=T,
        subject="alice",
        grants=GrantSet.of(["*"]),
        role="org-admin",
        actor_tier="human",
        scope={"all": True},
        active_workspace_id=workspace_id,
    )


async def _seed() -> Kernel:
    store = InMemoryStore()
    kernel = Kernel(store)
    items = (
        WorkItem(
            id="run-org",
            tenant_id=T,
            source="internal",
            intent="org task",
            confidence=1.0,
            convergent=True,
            status=WorkStatus.IN_FLIGHT,
            owner_member="engineering",
            on_behalf_of="alice",
        ),
        WorkItem(
            id="work-ws1",
            tenant_id=T,
            source="internal",
            intent="ws1 task",
            confidence=1.0,
            convergent=True,
            status=WorkStatus.IN_FLIGHT,
            owner_member="engineering",
            on_behalf_of="alice",
            hatchet_run_id="run-ws1",
            workspace_id="ws-1",
        ),
        WorkItem(
            id="child-ws1",
            tenant_id=T,
            source="internal",
            intent="visible child",
            confidence=1.0,
            convergent=True,
            parent_id="work-ws1",
            owner_member="engineering",
            workspace_id="ws-1",
        ),
        WorkItem(
            id="child-ws2",
            tenant_id=T,
            source="internal",
            intent="hidden child",
            confidence=1.0,
            convergent=True,
            parent_id="work-ws1",
            owner_member="engineering",
            workspace_id="ws-2",
        ),
        WorkItem(
            id="work-ws2",
            tenant_id=T,
            source="internal",
            intent="ws2 secret task",
            confidence=1.0,
            convergent=True,
            status=WorkStatus.IN_FLIGHT,
            owner_member="engineering",
            on_behalf_of="alice",
            hatchet_run_id="run-ws2",
            workspace_id="ws-2",
        ),
        WorkItem(
            id="run-collision",
            tenant_id=T,
            source="internal",
            intent="hidden direct id",
            confidence=1.0,
            convergent=True,
            owner_member="engineering",
            workspace_id="ws-2",
        ),
        WorkItem(
            id="visible-alias",
            tenant_id=T,
            source="internal",
            intent="visible colliding alias",
            confidence=1.0,
            convergent=True,
            owner_member="engineering",
            hatchet_run_id="run-collision",
            workspace_id="ws-1",
        ),
    )
    for item in items:
        await store.create_work_item(item)
    for workflow_id, workspace_id in (("wf-ws1", "ws-1"), ("wf-ws2", "ws-2")):
        await store.upsert_workflow(
            WorkflowDefinition(
                id=workflow_id,
                tenant_id=T,
                version="1.0.0",
                source=WorkflowSource.LEARNED,
                definition={"steps": []},
                workspace_id=workspace_id,
            )
        )

    events = (
        ("run-org", None, None, "org-model", "org-actor", 1),
        ("run-ws1", None, "ws-1", "ws1-model", "ws1-actor", 10),
        ("run-ws1", None, None, "ws1-null-model", "ws1-null-actor", 2),
        ("run-ws1", None, "ws-2", "bad-stamp-model", "audit-secret", 1000),
        ("run-ws2", "run-ws1", None, "ws2-secret-model", "ws2-secret", 100),
        ("run-collision", None, None, "collision-secret-model", "collision-secret", 200),
        ("run-audit-only", None, "ws-1", "audit-only-model", "audit-only", 5),
    )
    for run_id, parent_id, workspace_id, model, actor, cost in events:
        await kernel.audit.write(
            AuditEvent(
                tenant_id=T,
                ts=utcnow(),
                run_id=run_id,
                parent_run_id=parent_id,
                workspace_id=workspace_id,
                actor=actor,
                actor_tier="ephemeral",
                action_type=ActionType.MODEL_CALL,
                status="ok",
                verb="model.invoke",
                cost_micros=cost,
                tokens_used=1,
                detail={"model_route": {"model": model, "provider": "test"}},
            )
        )
    await store.record_workflow_run(T, "wf-ws1", "run-org", "completed")
    await store.record_workflow_run(T, "wf-ws1", "run-audit-only", "completed")
    await store.record_workflow_run(T, "wf-ws1", "run-ws2", "completed")
    await store.record_workflow_run(T, "wf-ws2", "run-ws2", "completed")
    return kernel


def _client(kernel: Kernel) -> TestClient:
    principals = {"ws1": _principal("ws-1"), "none": _principal(None)}

    async def resolver(request: Request) -> Principal:
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        principal = principals.get(token)
        if principal is None:
            raise HTTPException(status_code=401, detail="unauthenticated")
        return principal

    return TestClient(create_app(kernel, principal_resolver=resolver, platform={}))


def _get(client: TestClient, path: str, token: str = "ws1"):
    return client.get(path, headers={"authorization": f"Bearer {token}"})


@pytest.mark.security
@pytest.mark.invariant("SEC-142")
def test_work_list_detail_children_and_audit_are_workspace_scoped():
    client = _client(asyncio.run(_seed()))

    listed = _get(client, "/v1/work").json()["items"]
    assert {row["id"] for row in listed} == {
        "run-org",
        "work-ws1",
        "child-ws1",
        "visible-alias",
    }
    no_active = _get(client, "/v1/work", "none").json()["items"]
    assert {row["id"] for row in no_active} == {"run-org"}

    detail = _get(client, "/v1/work/work-ws1")
    assert detail.status_code == 200
    assert {row["id"] for row in detail.json()["children"]} == {"child-ws1"}
    rendered = detail.text
    assert "ws1-actor" in rendered and "ws1-null-actor" in rendered
    assert "audit-secret" not in rendered

    hidden = _get(client, "/v1/work/work-ws2")
    unknown = _get(client, "/v1/work/unknown")
    assert hidden.status_code == unknown.status_code == 404
    assert hidden.json() == unknown.json() == {"error": "not_found"}


@pytest.mark.security
@pytest.mark.invariant("SEC-142")
def test_run_lists_streams_trees_and_cancel_bind_to_workitem_workspace():
    kernel = asyncio.run(_seed())
    client = _client(kernel)

    runs = {row["run_id"] for row in _get(client, "/v1/runs").json()["runs"]}
    assert runs == {"run-org", "run-ws1", "child-ws1"}
    no_active = {
        row["run_id"] for row in _get(client, "/v1/runs", "none").json()["runs"]
    }
    assert no_active == {"run-org"}

    assert _get(client, "/v1/runs/run-org/events").status_code == 200
    assert _get(client, "/v1/runs/run-audit-only/events").status_code == 200
    for run_id in ("run-ws2", "run-collision"):
        assert _get(client, f"/v1/runs/{run_id}/events").status_code == 404
        assert _get(client, f"/v1/audit/tree/{run_id}").status_code == 404
    assert _get(client, "/v1/runs/run-audit-only/events", "none").status_code == 404

    tree = _get(client, "/v1/audit/tree/run-ws1")
    assert tree.status_code == 200
    assert "run-ws2" not in tree.text and "ws2-secret" not in tree.text
    assert _get(client, "/v1/audit/tree/run-audit-only").status_code == 200

    async def seed_hidden_parent_edge():
        await kernel.store.create_work_item(
            WorkItem(
                id="run-hidden-parent",
                tenant_id=T,
                source="internal",
                intent="hidden parent",
                confidence=1.0,
                convergent=True,
                workspace_id="ws-2",
            )
        )
        await kernel.store.create_work_item(
            WorkItem(
                id="run-visible-child",
                tenant_id=T,
                source="internal",
                intent="visible child with hidden parent",
                confidence=1.0,
                convergent=True,
                workspace_id="ws-1",
            )
        )
        await kernel.audit.write(
            AuditEvent(
                tenant_id=T,
                ts=utcnow(),
                run_id="run-visible-child",
                parent_run_id="run-hidden-parent",
                workspace_id="ws-1",
                actor="visible-child",
                actor_tier="ephemeral",
                action_type=ActionType.AGENT_SPAWN,
                status="ok",
            )
        )

    asyncio.run(seed_hidden_parent_edge())
    parent_leak = _get(client, "/v1/audit/tree/run-visible-child")
    assert parent_leak.status_code == 200
    assert parent_leak.json()["root"]["parent_run_id"] is None
    assert "run-hidden-parent" not in parent_leak.text

    workflow_runs = _get(client, "/v1/workflows/wf-ws1/runs")
    assert workflow_runs.status_code == 200
    assert set(workflow_runs.json()["runs"]) == {"run-org", "run-audit-only"}
    assert _get(client, "/v1/workflows/wf-ws2/runs").status_code == 404

    headers = {"authorization": "Bearer ws1"}
    hidden = client.post("/v1/runs/run-ws2/cancel", headers=headers)
    unknown = client.post("/v1/runs/unknown/cancel", headers=headers)
    assert hidden.status_code == unknown.status_code == 404
    assert hidden.json() == unknown.json()
    assert not asyncio.run(kernel.store.is_run_cancel_requested(T, "run-ws2"))


@pytest.mark.security
@pytest.mark.invariant("SEC-142")
def test_console_cost_audit_and_model_views_reject_null_audit_for_hidden_work():
    client = _client(asyncio.run(_seed()))

    console = _get(client, "/v1/console/overview").json()
    console_text = str(console)
    assert "ws1-model" in console_text and "audit-only-model" in console_text
    assert "ws2-secret-model" not in console_text
    assert "collision-secret-model" not in console_text

    models = _get(client, "/v1/model/telemetry").json()["models"]
    model_names = {row["model"] for row in models}
    assert {"org-model", "ws1-model", "ws1-null-model", "audit-only-model"} <= model_names
    assert not {"ws2-secret-model", "collision-secret-model"} & model_names

    audit = _get(client, "/v1/audit/search").json()["results"]
    actors = {row["actor"] for row in audit}
    assert {"org-actor", "ws1-actor", "ws1-null-actor", "audit-only"} <= actors
    assert not {"ws2-secret", "collision-secret", "audit-secret"} & actors

    cost = _get(client, "/v1/cost").json()
    assert cost["total_cost_micros"] == 18
    assert not {"ws2-secret", "collision-secret", "audit-secret"} & set(
        cost["by_actor"]
    )

    no_active = _get(client, "/v1/cost", "none").json()
    assert no_active["total_cost_micros"] == 1
    assert no_active["by_actor"] == {"org-actor": 1}


@pytest.mark.security
@pytest.mark.invariant("SEC-142")
def test_tree_assembly_bounds_self_and_multi_node_cycles():
    from boltrig.observability.tree import tree_from_events

    def event(run_id: str, parent_id: str) -> AuditEvent:
        return AuditEvent(
            tenant_id=T,
            ts=utcnow(),
            run_id=run_id,
            parent_run_id=parent_id,
            actor="agent",
            actor_tier="ephemeral",
            action_type=ActionType.AGENT_SPAWN,
            status="ok",
            cost_micros=1,
        )

    self_cycle = tree_from_events([event("self", "self")], "self")["root"]
    assert self_cycle["total_cost_micros"] == 1
    assert self_cycle["children"][0]["degraded"] == "cycle"

    cycle = tree_from_events(
        [event("a", "c"), event("b", "a"), event("c", "b")], "a"
    )["root"]
    assert cycle["total_cost_micros"] == 3
    assert cycle["children"][0]["children"][0]["children"][0]["degraded"] == "cycle"
