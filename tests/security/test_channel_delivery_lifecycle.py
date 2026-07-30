"""Caller-safe channel delivery receipts and exact governed recovery."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    Channel,
    ChannelOutboxMessage,
    GrantSet,
    TenantPermissions,
)
from boltrig.store import InMemoryStore
from tests.approval import approved_request

T = "channel-delivery-lifecycle"
ADMIN = {
    "x-boltrig-tenant": T,
    "x-boltrig-subject": "channel-author",
    "x-boltrig-role": "org-admin",
}
MEMBER = {**ADMIN, "x-boltrig-role": "member"}


async def _kernel() -> tuple[Kernel, InMemoryStore]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    await store.upsert_channel(
        Channel(
            id="ch-socket",
            tenant_id=T,
            platform="slack",
            name="Operations",
            transport="socket",
            credential_ref="opaque-channel-credential",
            enabled=True,
        )
    )
    return Kernel(store), store


async def _terminal(store: InMemoryStore, message_id: str) -> None:
    await store.enqueue_channel_outbox(
        ChannelOutboxMessage(
            id=message_id,
            tenant_id=T,
            channel_id="ch-socket",
            payload={
                "text": "private message body",
                "target": "private destination",
                "credential": "never public",
            },
        )
    )
    claimed = await store.claim_channel_outbox(
        T, ["ch-socket"], "private-gateway-lease-owner", 60, 1
    )
    assert [row.id for row in claimed] == [message_id]
    assert await store.fail_channel_outbox(
        T,
        message_id,
        "private-gateway-lease-owner",
        "provider error includes private destination and credential",
        max_attempts=1,
        backoff_seconds=1,
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-29")
def test_delivery_receipts_are_author_scoped_bounded_and_metadata_only() -> None:
    kernel, store = asyncio.run(_kernel())
    asyncio.run(_terminal(store, "message-private"))
    client = TestClient(create_app(kernel))

    assert client.get(
        "/v1/channels/ch-socket/deliveries", headers=MEMBER
    ).status_code == 403
    assert client.get(
        "/v1/channels/not-a-channel/deliveries", headers=ADMIN
    ).status_code == 404

    response = client.get(
        "/v1/channels/ch-socket/deliveries?limit=500", headers=ADMIN
    )
    assert response.status_code == 200
    delivery = response.json()["deliveries"][0]
    assert set(delivery) == {
        "id",
        "channel_id",
        "status",
        "attempts",
        "safe_reason",
        "created_at",
        "updated_at",
        "next_attempt_at",
    }
    assert delivery == {
        "id": "message-private",
        "channel_id": "ch-socket",
        "status": "terminal_failed",
        "attempts": 1,
        "safe_reason": "delivery_failed",
        "created_at": delivery["created_at"],
        "updated_at": delivery["updated_at"],
        "next_attempt_at": None,
    }
    assert "private message body" not in response.text
    assert "private destination" not in response.text
    assert "credential" not in response.text
    assert "lease-owner" not in response.text
    assert "provider error" not in response.text


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-29")
def test_only_the_approved_exact_terminal_snapshot_can_be_requeued() -> None:
    kernel, store = asyncio.run(_kernel())
    asyncio.run(_terminal(store, "failed-exact"))
    client = TestClient(create_app(kernel))
    receipt = client.get(
        "/v1/channels/ch-socket/deliveries", headers=ADMIN
    ).json()["deliveries"][0]
    path = "/v1/channels/ch-socket/deliveries/failed-exact/retry"
    body = {"expected_updated_at": receipt["updated_at"]}

    held = client.post(path, headers=ADMIN, json=body)
    assert held.status_code == 202
    assert held.json()["status"] == "pending_human"
    approval_id = held.json()["hitl_request_id"]
    pending = client.get(
        f"/v1/invoke/approvals/{approval_id}", headers=ADMIN
    )
    assert pending.status_code == 200 and pending.json() == {"status": "pending"}
    hidden = client.get(
        f"/v1/invoke/approvals/{approval_id}",
        headers={**ADMIN, "x-boltrig-subject": "different-author"},
    )
    assert hidden.status_code == 404
    asyncio.run(
        kernel.hitl.answer(T, approval_id, "approve", "independent-reviewer")
    )
    approved_state = client.get(
        f"/v1/invoke/approvals/{approval_id}", headers=ADMIN
    )
    assert approved_state.json() == {"status": "approved"}
    approved = client.post(
        path,
        headers=ADMIN,
        json={**body, "approval_id": approval_id},
    )
    assert approved.status_code == 200
    assert approved.json()["delivery"]["status"] == "queued"
    assert approved.json()["delivery"]["attempts"] == 0

    # A terminal snapshot is single-use. It cannot become an arbitrary requeue
    # primitive for an already queued row.
    refused = client.post(path, headers=ADMIN, json=body)
    assert refused.status_code in {400, 409}
    current = asyncio.run(
        store.get_channel_delivery_receipt(T, "ch-socket", "failed-exact")
    )
    assert current is not None and current.status == "queued"


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-29")
def test_retry_approval_fails_closed_when_channel_configuration_changes() -> None:
    kernel, store = asyncio.run(_kernel())
    asyncio.run(_terminal(store, "failed-config-drift"))
    client = TestClient(create_app(kernel))
    receipt = client.get(
        "/v1/channels/ch-socket/deliveries", headers=ADMIN
    ).json()["deliveries"][0]
    path = "/v1/channels/ch-socket/deliveries/failed-config-drift/retry"
    body = {"expected_updated_at": receipt["updated_at"]}
    held = client.post(path, headers=ADMIN, json=body)
    assert held.status_code == 202

    channel = asyncio.run(store.get_channel(T, "ch-socket"))
    assert channel is not None
    channel.enabled = False
    asyncio.run(store.upsert_channel(channel))
    replay = approved_request(
        client,
        kernel,
        T,
        "POST",
        path,
        headers=ADMIN,
        json=body,
        held=held,
    )
    assert replay.status_code in {400, 403, 409}
    current = asyncio.run(
        store.get_channel_delivery_receipt(
            T, "ch-socket", "failed-config-drift"
        )
    )
    assert current is not None and current.status == "terminal_failed"
