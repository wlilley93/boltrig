"""Saved evaluation cases are author-scoped and tenant-isolated."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import EvalCase, GrantSet, TenantPermissions
from boltrig.store import InMemoryStore

TENANT = "acme"
OTHER = "globex"


def _headers(tenant: str = TENANT, role: str = "org-admin") -> dict[str, str]:
    return {
        "x-boltrig-tenant": tenant,
        "x-boltrig-subject": "eval-author",
        "x-boltrig-role": role,
        "x-boltrig-grants": "*",
    }


def _client() -> TestClient:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(TENANT, GrantSet.of(["*"])))
    store.set_tenant_permissions(TenantPermissions(OTHER, GrantSet.of(["*"])))
    cases = [
        EvalCase(
            id="z-last",
            tenant_id=TENANT,
            target_kind="workflow",
            target_ref="release",
            input={"version": "2.0"},
            assertions={"passed": True},
            labels=["release"],
        ),
        EvalCase(
            id="a-first",
            tenant_id=TENANT,
            target_kind="skill",
            target_ref="triage",
            input={"ticket": "42"},
            assertions={"forbidden_grants": ["ticket.delete"]},
            labels=["security", "regression"],
        ),
        EvalCase(
            id="foreign",
            tenant_id=OTHER,
            target_kind="skill",
            target_ref="private",
            input={"secret": True},
            assertions={},
        ),
    ]
    for case in cases:
        asyncio.run(store.upsert_eval_case(case))
    return TestClient(create_app(Kernel(store), platform={}))


@pytest.mark.security
def test_eval_case_listing_is_tenant_isolated_and_stable() -> None:
    response = _client().get("/v1/eval/cases", headers=_headers())

    assert response.status_code == 200
    assert response.json() == {
        "cases": [
            {
                "id": "a-first",
                "target_kind": "skill",
                "target_ref": "triage",
                "input": {"ticket": "42"},
                "assertions": {"forbidden_grants": ["ticket.delete"]},
                "labels": ["security", "regression"],
                "is_active": True,
                "status": "active",
            },
            {
                "id": "z-last",
                "target_kind": "workflow",
                "target_ref": "release",
                "input": {"version": "2.0"},
                "assertions": {"passed": True},
                "labels": ["release"],
                "is_active": True,
                "status": "active",
            },
        ]
    }


@pytest.mark.security
def test_eval_case_listing_rejects_non_authors() -> None:
    response = _client().get("/v1/eval/cases", headers=_headers(role="member"))

    assert response.status_code == 403
