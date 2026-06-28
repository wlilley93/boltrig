"""Row-level department isolation on /v1/work (US-IAM-02).

An engineer scoped to one department cannot list another department's work
queue; an org-admin sees everything. The filter is applied at the store, not the
handler, so a caller cannot widen it.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from nankle.kernel import Kernel
from nankle.kernel.app import create_app
from nankle.models import GrantSet, TenantPermissions, WorkItem, WorkStatus
from nankle.store import InMemoryStore

T = "acme"


def _client() -> TestClient:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))

    async def _seed():
        for wid, dept in [("w-eng", "engineering"), ("w-mkt", "marketing")]:
            await store.create_work_item(
                WorkItem(id=wid, tenant_id=T, source="internal", intent=f"{dept} task",
                         confidence=0.9, convergent=True, status=WorkStatus.PENDING,
                         owner_member=dept)
            )

    asyncio.run(_seed())
    return TestClient(create_app(Kernel(store)))


def _hdr(role: str, departments: str = ""):
    return {
        "x-nankle-tenant": T, "x-nankle-subject": "u",
        "x-nankle-role": role, "x-nankle-departments": departments,
    }


@pytest.mark.security
@pytest.mark.invariant("US-IAM-02")
def test_engineer_sees_only_their_department():
    r = _client().get("/v1/work", headers=_hdr("engineer", "engineering"))
    assert r.status_code == 200
    assert {w["id"] for w in r.json()["items"]} == {"w-eng"}


@pytest.mark.security
@pytest.mark.invariant("US-IAM-02")
def test_engineer_cannot_see_other_department():
    r = _client().get("/v1/work", headers=_hdr("engineer", "engineering"))
    assert "w-mkt" not in {w["id"] for w in r.json()["items"]}


@pytest.mark.security
def test_org_admin_sees_all_departments():
    r = _client().get("/v1/work", headers=_hdr("org-admin"))
    assert {w["id"] for w in r.json()["items"]} == {"w-eng", "w-mkt"}
