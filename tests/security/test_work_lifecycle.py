"""Governed Work board mutations stay behind dispatch and exact approval."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import GrantSet, TenantPermissions, WorkStatus, utcnow
from boltrig.store import InMemoryStore

T = "work-lifecycle"
H = {
    "x-boltrig-tenant": T,
    "x-boltrig-subject": "author",
    "x-boltrig-role": "org-admin",
    "x-boltrig-workspace": "workspace-a",
}


def _app() -> tuple[Kernel, TestClient]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    return kernel, TestClient(create_app(kernel))


def _create(client: TestClient, intent: str, **body) -> dict:
    response = client.post(
        "/v1/work",
        headers=H,
        json={"intent": intent, "idempotency_key": f"create-{intent}", **body},
    )
    assert response.status_code == 200, response.text
    return response.json()["item"]


async def _approve(
    kernel: Kernel,
    client: TestClient,
    path: str,
    body: dict,
) -> dict:
    held = client.patch(path, headers=H, json=body)
    assert held.status_code == 202
    request_id = held.json()["hitl_request_id"]
    await kernel.hitl.answer(T, request_id, "approve", "reviewer")
    applied = client.patch(
        path,
        headers={**H, "x-boltrig-approval-id": request_id},
        json=body,
    )
    assert applied.status_code == 200, applied.text
    return applied.json()["item"]


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-15")
@pytest.mark.invariant("SEC-WRK-32")
async def test_work_create_assign_status_and_audit_are_canonical() -> None:
    kernel, client = _app()
    created = _create(client, "Prepare launch", owner_member="engineering")
    assert created["source"] == "internal"
    stored = await kernel.store.get_work_item(T, created["id"])
    assert stored.workspace_id == "workspace-a"
    assert stored.on_behalf_of == "author"

    assigned = client.patch(
        f"/v1/work/{created['id']}/assignment",
        headers=H,
        json={"owner_member": None, "idempotency_key": "unassign-1"},
    )
    assert assigned.status_code == 200
    assert assigned.json()["item"]["owner_member"] is None

    blocked = await _approve(
        kernel,
        client,
        f"/v1/work/{created['id']}/status",
        {"status": "blocked", "idempotency_key": "status-1"},
    )
    assert blocked["status"] == WorkStatus.BLOCKED.value

    events = await kernel.store.audit_query(T)
    create_event = next(e for e in events if e.verb == "control.work.create")
    assert create_event.detail["params"] == {
        "keys": ["intent", "owner_member"],
        "count": 2,
    }
    assert "Prepare launch" not in repr(create_event.detail)


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-16")
@pytest.mark.invariant("SEC-WRK-32")
async def test_work_approval_is_bound_to_the_exact_mutable_item() -> None:
    kernel, client = _app()
    item = _create(client, "Mutable", owner_member="engineering")
    path = f"/v1/work/{item['id']}/status"
    body = {"status": "blocked"}
    held = client.patch(path, headers=H, json=body)
    request_id = held.json()["hitl_request_id"]

    changed = client.patch(
        f"/v1/work/{item['id']}/assignment",
        headers=H,
        json={"owner_member": "operations", "idempotency_key": "drift"},
    )
    assert changed.status_code == 200
    await kernel.hitl.answer(T, request_id, "approve", "reviewer")
    refused = client.patch(
        path,
        headers={**H, "x-boltrig-approval-id": request_id},
        json=body,
    )
    # The changed resource no longer matches the exact approval fingerprint, so
    # the old approval cannot be consumed. The gate honestly holds a fresh
    # request instead of executing under stale authority.
    assert refused.status_code == 202
    assert refused.json()["hitl_request_id"] != request_id
    assert (await kernel.store.get_work_item(T, item["id"])).status is WorkStatus.PENDING


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-16")
async def test_work_change_between_gate_and_adapter_write_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel, client = _app()
    item = _create(client, "Race", owner_member="engineering")
    path = f"/v1/work/{item['id']}/status"
    body = {"status": "blocked"}
    held = client.patch(path, headers=H, json=body)
    request_id = held.json()["hitl_request_id"]
    await kernel.hitl.answer(T, request_id, "approve", "reviewer")

    original_get = kernel.store.get_work_item
    reads = 0

    async def drifting_get(*args, **kwargs):
        nonlocal reads
        current = await original_get(*args, **kwargs)
        reads += 1
        return current if reads == 1 else replace(current, owner_member="operations")

    monkeypatch.setattr(kernel.store, "get_work_item", drifting_get)
    refused = client.patch(
        path,
        headers={**H, "x-boltrig-approval-id": request_id},
        json=body,
    )
    assert refused.status_code == 403
    assert reads == 2
    assert (await original_get(T, item["id"])).status is WorkStatus.PENDING


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-17")
async def test_scope_cycle_and_live_lease_mutations_fail_closed() -> None:
    kernel, client = _app()
    root = _create(client, "Root", owner_member="engineering")
    child = _create(
        client, "Child", owner_member="engineering", parent_id=root["id"]
    )
    path_wins = client.patch(
        f"/v1/work/{child['id']}/assignment",
        headers=H,
        json={"item_id": root["id"], "owner_member": "operations"},
    )
    assert path_wins.status_code == 200
    assert (await kernel.store.get_work_item(T, child["id"])).owner_member == "operations"
    assert (await kernel.store.get_work_item(T, root["id"])).owner_member == "engineering"

    hidden_headers = {
        **H,
        "x-boltrig-role": "department-head",
        "x-boltrig-departments": "sales",
        "x-boltrig-verbs": "control.*",
    }
    hidden = client.patch(
        f"/v1/work/{child['id']}/assignment",
        headers=hidden_headers,
        json={"owner_member": "sales"},
    )
    assert hidden.status_code == 404
    missing_parent = client.post(
        "/v1/work",
        headers=H,
        json={"intent": "Orphan", "parent_id": "does-not-exist"},
    )
    assert missing_parent.status_code == 404

    cycle = client.patch(
        f"/v1/work/{root['id']}/parent",
        headers=H,
        json={"parent_id": child["id"]},
    )
    assert cycle.status_code == 202
    cycle_id = cycle.json()["hitl_request_id"]
    await kernel.hitl.answer(T, cycle_id, "approve", "reviewer")
    rejected = client.patch(
        f"/v1/work/{root['id']}/parent",
        headers={**H, "x-boltrig-approval-id": cycle_id},
        json={"parent_id": child["id"]},
    )
    assert rejected.status_code == 400

    stored_child = await kernel.store.get_work_item(T, child["id"])
    stored_child.lease_owner = "worker"
    stored_child.lease_expires_at = utcnow() + timedelta(minutes=5)
    await kernel.store.update_work_item(stored_child)
    leased = client.patch(
        f"/v1/work/{child['id']}/assignment",
        headers=H,
        json={"owner_member": "operations"},
    )
    assert leased.status_code == 409
