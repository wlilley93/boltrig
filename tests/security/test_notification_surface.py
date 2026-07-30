"""Worker notification options must be exact, deliverable, and caller-scoped."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    Channel,
    ChannelBinding,
    GrantSet,
    NotificationPref,
    TenantPermissions,
)
from boltrig.store import InMemoryStore

T = "notification-tenant"


def _headers(subject: str = "alice") -> dict[str, str]:
    return {
        "x-boltrig-tenant": T,
        "x-boltrig-subject": subject,
        "x-boltrig-role": "member",
        "x-boltrig-grants": "*",
    }


async def _kernel() -> tuple[Kernel, InMemoryStore]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    for channel in (
        Channel(
            id="ch-slack",
            tenant_id=T,
            platform="slack",
            name="Operations",
            transport="socket",
            credential_ref="secret/channel/slack",
        ),
        Channel(
            id="ch-webhook",
            tenant_id=T,
            platform="webhook",
            name="Webhook",
            transport="webhook",
        ),
        Channel(
            id="ch-unbound",
            tenant_id=T,
            platform="msteams",
            name="Unbound Teams",
            transport="socket",
        ),
        Channel(
            id="ch-disabled",
            tenant_id=T,
            platform="telegram",
            name="Disabled Telegram",
            transport="socket",
            enabled=False,
        ),
    ):
        await store.upsert_channel(channel)
    await store.upsert_channel_binding(
        ChannelBinding(
            id="binding-alice",
            tenant_id=T,
            channel_id="ch-slack",
            platform="slack",
            external_user_id="U-alice",
            subject="alice",
            role="member",
        )
    )
    return kernel, store


def _approved_put(client, kernel, body, *, subject="alice"):
    held = client.put("/v1/me/notifications", json=body, headers=_headers(subject))
    assert held.status_code == 202
    request_id = held.json()["hitl_request_id"]
    asyncio.run(kernel.hitl.answer(T, request_id, "approve", "reviewer"))
    return client.put(
        "/v1/me/notifications",
        json=body,
        headers={
            **_headers(subject),
            "x-boltrig-approval-id": request_id,
        },
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-11")
def test_notification_catalogue_exposes_only_real_events_and_bound_transports():
    kernel, store = asyncio.run(_kernel())
    client = TestClient(create_app(kernel))
    response = client.get("/v1/me/notifications", headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert [event["id"] for event in body["catalogue"]["events"]] == [
        "approval",
        "escalation",
        "hitl_expired",
        "work_status",
    ]
    assert body["catalogue"]["transports"] == [
        {
            "id": "ch-slack",
            "platform": "slack",
            "label": "Operations",
            "delivery_mode": "durable_outbox",
            "targets": [
                {
                    "id": "U-alice",
                    "label": "Verified slack identity",
                }
            ],
        }
    ]
    assert "secret/channel/slack" not in response.text
    assert not {"in_app", "email", "budget_alert", "error"} & {
        event["id"] for event in body["catalogue"]["events"]
    }
    assert (
        client.get("/v1/me/notifications", headers=_headers("bob")).json()["catalogue"][
            "transports"
        ]
        == []
    )
    assert store is kernel.store


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-11")
def test_notification_routes_are_replacement_safe_and_report_delivery_status():
    kernel, store = asyncio.run(_kernel())
    client = TestClient(create_app(kernel))
    created = _approved_put(
        client,
        kernel,
        {
            "event_type": "approval",
            "channel": "ch-slack",
            "target": "U-alice",
            "enabled": True,
        },
    )
    assert created.status_code == 200, created.text
    preference_id = created.json()["id"]

    test = client.post(
        f"/v1/me/notifications/{preference_id}/test",
        headers=_headers(),
    )
    assert test.status_code == 200
    assert test.json()["delivery_status"] == "queued"
    delivery_id = test.json()["delivery_id"]
    listed = client.get("/v1/me/notifications", headers=_headers()).json()
    last_delivery = listed["prefs"][0]["last_delivery"]
    assert last_delivery["id"] == delivery_id
    assert last_delivery["status"] == "pending"
    assert isinstance(last_delivery["updated_at"], str)

    (claimed,) = asyncio.run(store.claim_channel_outbox(T, ["ch-slack"], "gateway", 60, 10))
    assert claimed.payload["test"] is True
    assert claimed.payload["target"] == "U-alice"
    assert "notification_pref_id" not in claimed.payload
    in_flight = client.get("/v1/me/notifications", headers=_headers()).json()
    assert in_flight["prefs"][0]["last_delivery"]["status"] == "in_flight"
    asyncio.run(store.ack_channel_outbox(T, delivery_id, "gateway"))
    delivered = client.get("/v1/me/notifications", headers=_headers()).json()
    assert delivered["prefs"][0]["last_delivery"]["status"] == "delivered"

    failed_test = client.post(
        f"/v1/me/notifications/{preference_id}/test",
        headers=_headers(),
    )
    failed_delivery_id = failed_test.json()["delivery_id"]
    asyncio.run(store.claim_channel_outbox(T, ["ch-slack"], "gateway", 60, 10))
    asyncio.run(
        store.fail_channel_outbox(
            T,
            failed_delivery_id,
            "gateway",
            "bounded test failure",
            max_attempts=1,
            backoff_seconds=1,
        )
    )
    failed = client.get("/v1/me/notifications", headers=_headers()).json()
    assert failed["prefs"][0]["last_delivery"]["status"] == "failed"

    asyncio.run(
        store.upsert_notification_pref(
            NotificationPref(
                id="bob-route",
                tenant_id=T,
                scope_kind="user",
                scope_ref="bob",
                event_type="approval",
                channel="ch-slack",
                target="U-bob",
            )
        )
    )
    stolen = _approved_put(
        client,
        kernel,
        {
            "id": "bob-route",
            "event_type": "approval",
            "channel": "ch-slack",
            "target": "U-alice",
            "enabled": False,
        },
    )
    assert stolen.status_code == 404
    bob = next(
        item for item in asyncio.run(store.list_notification_prefs(T)) if item.id == "bob-route"
    )
    assert bob.scope_ref == "bob" and bob.enabled is True


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-11")
def test_notification_write_rejects_unproduced_events_and_unverified_targets():
    kernel, store = asyncio.run(_kernel())
    client = TestClient(create_app(kernel))
    unproduced = _approved_put(
        client,
        kernel,
        {
            "event_type": "budget_alert",
            "channel": "ch-slack",
            "target": "U-alice",
        },
    )
    assert unproduced.status_code == 400
    assert unproduced.json()["reason"] == "adapter_invalid"

    unverified = _approved_put(
        client,
        kernel,
        {
            "event_type": "approval",
            "channel": "ch-slack",
            "target": "C-arbitrary",
        },
    )
    assert unverified.status_code == 400
    assert unverified.json()["reason"] == "adapter_invalid"
    assert asyncio.run(store.list_notification_prefs(T)) == []
