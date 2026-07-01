"""The work-item detail endpoint returns the epic->story tree + audit trail,
scope-filtered by department (US-IAM-02; #74 work-board backend).
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    ActionType,
    AuditEvent,
    GrantSet,
    TenantPermissions,
    WorkItem,
    WorkStatus,
    utcnow,
)
from boltrig.store import InMemoryStore

T = "acme"


def _client() -> TestClient:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))

    async def _seed():
        await store.create_work_item(
            WorkItem(id="epic-1", tenant_id=T, source="slack", intent="litigation matter",
                     confidence=0.9, convergent=False, status=WorkStatus.IN_FLIGHT,
                     owner_member="engineering", hatchet_run_id="run-1")
        )
        await store.create_work_item(
            WorkItem(id="story-1", tenant_id=T, source="internal", intent="draft filing",
                     confidence=0.8, convergent=True, status=WorkStatus.PENDING,
                     owner_member="engineering", parent_id="epic-1")
        )
        await store.create_work_item(
            WorkItem(id="mkt-1", tenant_id=T, source="internal", intent="campaign",
                     confidence=0.9, convergent=True, status=WorkStatus.PENDING,
                     owner_member="marketing")
        )
        await store.audit_append(
            AuditEvent(tenant_id=T, ts=utcnow(), actor="cos", action_type=ActionType.TOOL_CALL,
                       status="ok", run_id="run-1", actor_tier="tier1", noun="work",
                       verb="work.route")
        )

    asyncio.run(_seed())
    return TestClient(create_app(Kernel(store)))


def _hdr(role: str, departments: str = ""):
    return {
        "x-boltrig-tenant": T, "x-boltrig-subject": "u",
        "x-boltrig-role": role, "x-boltrig-departments": departments,
    }


@pytest.mark.security
@pytest.mark.invariant("US-IAM-02")
def test_work_detail_returns_children_and_audit():
    r = _client().get("/v1/work/epic-1", headers=_hdr("engineer", "engineering"))
    assert r.status_code == 200
    body = r.json()
    assert body["item"]["id"] == "epic-1"
    assert {c["id"] for c in body["children"]} == {"story-1"}  # the tree
    assert any(e["verb"] == "work.route" for e in body["audit"])  # the trail


@pytest.mark.security
@pytest.mark.invariant("US-IAM-02")
def test_work_detail_scope_isolation():
    # an engineer cannot open a marketing item: it is outside their visible set -> 404
    r = _client().get("/v1/work/mkt-1", headers=_hdr("engineer", "engineering"))
    assert r.status_code == 404
