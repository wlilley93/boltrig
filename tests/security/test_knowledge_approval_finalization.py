"""Exact caller-lane continuation for fixed Knowledge mutations."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.knowledge import register_knowledge
from boltrig.models import GrantSet, TenantPermissions
from boltrig.store import InMemoryStore

T = "knowledge-approval-finalization"
AUTHOR = {
    "x-boltrig-tenant": T,
    "x-boltrig-subject": "knowledge-author",
    "x-boltrig-role": "org-admin",
}


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-32")
async def test_provider_change_replays_only_with_the_exact_approved_route_input(
    tmp_path,
) -> None:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    await register_knowledge(
        kernel,
        T,
        {
            "enabled": True,
            "vault": {"kind": "filesystem", "root": str(tmp_path / "vault")},
        },
    )
    client = TestClient(create_app(kernel))

    pending = client.post(
        "/v1/knowledge/providers/cognee",
        json={"enabled": False},
        headers=AUTHOR,
    )
    assert pending.status_code == 202
    request_id = pending.json()["hitl_request_id"]

    await kernel.hitl.answer(T, request_id, "approve", "independent-reviewer")
    changed_input = client.post(
        "/v1/knowledge/providers/cognee",
        json={"enabled": True},
        headers={**AUTHOR, "x-boltrig-approval-id": request_id},
    )
    # The gate rejects the mismatched fingerprint and creates a distinct
    # approval rather than spending the original authorization.
    assert changed_input.status_code == 202
    assert changed_input.json()["hitl_request_id"] != request_id

    completed = client.post(
        "/v1/knowledge/providers/cognee",
        json={"enabled": False},
        headers={**AUTHOR, "x-boltrig-approval-id": request_id},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "ok"
    assert completed.json()["provider"]["enabled"] is False
