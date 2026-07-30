"""Caller-owned channel approval finalization and mutable-resource binding."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import Channel, GrantSet, TenantPermissions
from boltrig.store import InMemoryStore


TENANT = "channel-approval-finalization"
ADMIN = {
    "x-boltrig-tenant": TENANT,
    "x-boltrig-subject": "channel-author",
    "x-boltrig-role": "org-admin",
}


def _setup() -> tuple[Kernel, InMemoryStore, TestClient]:
    store = InMemoryStore()
    store.set_tenant_permissions(
        TenantPermissions(TENANT, GrantSet.of(["*"]))
    )
    asyncio.run(
        store.upsert_channel(
            Channel(
                id="channel-exact",
                tenant_id=TENANT,
                platform="webhook",
                name="Support",
                transport="webhook",
                enabled=True,
                unpaired_behavior="pair",
            )
        )
    )
    kernel = Kernel(store)
    return kernel, store, TestClient(create_app(kernel))


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-32")
def test_pairing_discovery_is_requester_owned_and_code_is_created_once() -> None:
    kernel, _store, client = _setup()
    path = "/v1/channels/channel-exact/pair"
    body = {
        "external_user_id": "sender-42",
        "subject": "user:alice",
        "role": "member",
        "ttl_minutes": 20,
    }

    held = client.post(path, headers=ADMIN, json=body)
    assert held.status_code == 202
    request_id = held.json()["hitl_request_id"]
    assert "code" not in held.json()

    discovery_path = "/v1/channels/channel-exact/pair-finalizations"
    waiting = client.get(discovery_path, headers=ADMIN)
    assert waiting.status_code == 200
    assert waiting.json() == {
        "channel_id": "channel-exact",
        "finalizations": [{
            "request_id": request_id,
            "state": "waiting",
            "external_user_id": "sender-42",
            "subject": "user:alice",
            "role": "member",
            "ttl_minutes": 20,
        }],
    }
    assert all(
        "code" not in item for item in waiting.json()["finalizations"]
    )
    hidden = client.get(
        discovery_path,
        headers={**ADMIN, "x-boltrig-subject": "different-author"},
    )
    assert hidden.status_code == 200
    assert hidden.json()["finalizations"] == []

    asyncio.run(
        kernel.hitl.answer(
            TENANT, request_id, "approve", "independent-reviewer"
        )
    )
    ready = client.get(discovery_path, headers=ADMIN)
    assert ready.status_code == 200
    assert ready.json()["finalizations"][0]["state"] == "ready"
    assert "code" not in ready.json()["finalizations"][0]

    issued = client.post(
        path,
        headers={**ADMIN, "x-boltrig-approval-id": request_id},
        json=body,
    )
    assert issued.status_code == 201
    assert issued.json()["status"] == "ok"
    assert issued.json()["code"]

    consumed = client.get(discovery_path, headers=ADMIN)
    assert consumed.status_code == 200
    assert consumed.json()["finalizations"] == []
    replay = client.post(
        path,
        headers={**ADMIN, "x-boltrig-approval-id": request_id},
        json=body,
    )
    assert replay.status_code == 409
    assert "code" not in replay.json()


@pytest.mark.security
@pytest.mark.invariant("SEC-138")
@pytest.mark.invariant("SEC-193")
def test_channel_configuration_approval_fails_closed_after_resource_drift() -> None:
    kernel, store, client = _setup()
    path = "/v1/channels/channel-exact"
    body = {"name": "Approved name", "enabled": True}
    held = client.patch(path, headers=ADMIN, json=body)
    assert held.status_code == 202
    request_id = held.json()["hitl_request_id"]

    channel = asyncio.run(store.get_channel(TENANT, "channel-exact"))
    assert channel is not None
    channel.enabled = False
    asyncio.run(store.upsert_channel(channel))
    asyncio.run(
        kernel.hitl.answer(
            TENANT, request_id, "approve", "independent-reviewer"
        )
    )

    replay = client.patch(
        path,
        headers={**ADMIN, "x-boltrig-approval-id": request_id},
        json=body,
    )
    assert replay.status_code == 202
    assert replay.json()["hitl_request_id"] != request_id
    current = asyncio.run(store.get_channel(TENANT, "channel-exact"))
    assert current is not None
    assert current.name == "Support"
    assert current.enabled is False
