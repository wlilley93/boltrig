"""HTTP regressions for tenant/department/workspace-scoped audit trees."""

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
    WorkItem,
    WorkStatus,
    utcnow,
)
from boltrig.store import InMemoryStore

T = "acme"


def _principal(
    *,
    tenant: str = T,
    subject: str = "reader",
    role: str = "engineer",
    departments: list[str] | None = None,
    workspace: str | None = "ws-1",
) -> Principal:
    scope = {"all": True} if role == "org-admin" else {"departments": departments or []}
    return Principal(
        tenant_id=tenant,
        subject=subject,
        grants=GrantSet.of(["*"]),
        role=role,
        actor_tier="human",
        scope=scope,
        active_workspace_id=workspace,
    )


async def _seed() -> Kernel:
    store = InMemoryStore()
    kernel = Kernel(store)
    work = (
        ("work-root", "engineering", "run-root"),
        ("work-eng", "engineering", "run-eng-child"),
        ("work-mkt", "marketing", "run-mkt-child"),
        ("work-ws2", "engineering", "run-ws2-child"),
        ("work-synthetic-root", "engineering", "run-synthetic-root"),
        ("work-synthetic-child", "engineering", "run-synthetic-child"),
        ("work-child-only-root", "engineering", "run-child-only-root"),
        ("work-child-only-child", "engineering", "run-child-only-child"),
    )
    for item_id, department, run_id in work:
        await store.create_work_item(
            WorkItem(
                id=item_id,
                tenant_id=T,
                source="internal",
                intent=item_id,
                confidence=1.0,
                convergent=True,
                status=WorkStatus.DONE,
                owner_member=department,
                hatchet_run_id=run_id,
            )
        )

    events = (
        ("run-root", None, "ws-1", "root-agent", 10, 1),
        ("run-eng-child", "run-root", None, "eng-agent", 20, 2),
        ("run-mkt-child", "run-root", "ws-1", "marketing-secret-agent", 999, 99),
        ("run-ws2-child", "run-root", "ws-2", "workspace-secret-agent", 777, 77),
        ("run-synthetic-root", None, "ws-2", "hidden-root-agent", 60, 6),
        ("run-synthetic-child", "run-synthetic-root", "ws-1", "child-agent", 50, 5),
        ("run-child-only-child", "run-child-only-root", "ws-1", "child-agent", 40, 4),
    )
    for run_id, parent_run_id, workspace_id, actor, cost, tokens in events:
        await kernel.audit.write(
            AuditEvent(
                tenant_id=T,
                ts=utcnow(),
                run_id=run_id,
                parent_run_id=parent_run_id,
                workspace_id=workspace_id,
                actor=actor,
                actor_tier="ephemeral",
                action_type=ActionType.TOOL_CALL,
                status="ok",
                verb="ticket.read",
                cost_micros=cost,
                tokens_used=tokens,
            )
        )
    return kernel


def _client(kernel: Kernel) -> TestClient:
    principals = {
        "eng": _principal(departments=["engineering"]),
        "admin": _principal(role="org-admin", workspace="ws-1"),
        "no-workspace": _principal(role="org-admin", workspace=None),
        "rival": _principal(tenant="rival", role="org-admin", workspace=None),
    }

    async def resolver(request: Request) -> Principal:
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        principal = principals.get(token)
        if principal is None:
            raise HTTPException(status_code=401, detail="unauthenticated")
        return principal

    return TestClient(create_app(kernel, principal_resolver=resolver, platform={}))


def _get(client: TestClient, run_id: str, token: str = "eng"):
    return client.get(
        f"/v1/audit/tree/{run_id}",
        headers={"authorization": f"Bearer {token}"},
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-33")
@pytest.mark.invariant("FR-OBS-02")
def test_audit_tree_denies_cross_department_root_and_prunes_every_hidden_node():
    client = _client(asyncio.run(_seed()))

    denied = _get(client, "run-mkt-child")
    assert denied.status_code == 404
    assert denied.json() == {"error": "unknown_run"}
    assert "marketing-secret-agent" not in denied.text

    visible = _get(client, "run-root")
    assert visible.status_code == 200
    body = visible.json()
    assert body["root"]["run_id"] == "run-root"
    assert body["root"]["total_cost_micros"] == 30
    assert [child["run_id"] for child in body["root"]["children"]] == ["run-eng-child"]
    rendered = visible.text
    assert "run-mkt-child" not in rendered
    assert "marketing-secret-agent" not in rendered
    assert "999" not in rendered


@pytest.mark.security
@pytest.mark.invariant("SEC-123")
def test_audit_tree_denies_cross_workspace_root_and_prunes_workspace_descendants():
    client = _client(asyncio.run(_seed()))

    denied = _get(client, "run-ws2-child")
    assert denied.status_code == 404
    assert denied.json() == {"error": "unknown_run"}

    visible = _get(client, "run-root")
    assert visible.status_code == 200
    assert "run-ws2-child" not in visible.text
    assert "workspace-secret-agent" not in visible.text
    assert visible.json()["root"]["total_cost_micros"] == 30


@pytest.mark.security
@pytest.mark.invariant("SEC-33")
def test_audit_tree_unknown_and_foreign_tenant_are_indistinguishable_404s():
    client = _client(asyncio.run(_seed()))
    unknown = _get(client, "does-not-exist")
    foreign = _get(client, "run-root", token="rival")
    assert unknown.status_code == foreign.status_code == 404
    assert unknown.json() == foreign.json() == {"error": "unknown_run"}


@pytest.mark.security
@pytest.mark.invariant("SEC-33")
@pytest.mark.invariant("FR-OBS-02")
def test_audit_tree_rejects_parent_only_when_root_rows_were_scope_filtered():
    client = _client(asyncio.run(_seed()))
    response = _get(client, "run-synthetic-root")
    assert response.status_code == 404
    assert response.json() == {"error": "unknown_run"}


@pytest.mark.security
@pytest.mark.invariant("FR-OBS-02")
def test_audit_tree_preserves_legitimate_child_only_root():
    client = _client(asyncio.run(_seed()))
    response = _get(client, "run-child-only-root")
    assert response.status_code == 200
    root = response.json()["root"]
    assert root["run_id"] == "run-child-only-root"
    assert [child["run_id"] for child in root["children"]] == [
        "run-child-only-child"
    ]


@pytest.mark.security
@pytest.mark.invariant("FR-OBS-02")
def test_unrestricted_audit_tree_preserves_complete_authorized_aggregate():
    client = _client(asyncio.run(_seed()))
    response = _get(client, "run-root", token="admin")
    assert response.status_code == 200
    root = response.json()["root"]
    assert root["total_cost_micros"] == 1029
    assert {child["run_id"] for child in root["children"]} == {
        "run-eng-child",
        "run-mkt-child",
    }


@pytest.mark.security
@pytest.mark.invariant("SEC-142")
def test_no_active_workspace_sees_only_org_wide_audit_rows():
    client = _client(asyncio.run(_seed()))
    response = _get(client, "run-root", token="no-workspace")
    assert response.status_code == 404
    assert response.json() == {"error": "unknown_run"}
