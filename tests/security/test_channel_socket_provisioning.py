"""Canonical socket-channel desired/observed provisioning (SEC-177)."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import GrantSet, TenantPermissions
from boltrig.store import InMemoryStore
from tests.approval import approved_request

T = "socket-provisioning"
ADMIN = {
    "x-boltrig-tenant": T,
    "x-boltrig-role": "org-admin",
    "x-boltrig-subject": "root",
}


def _kernel() -> tuple[Kernel, InMemoryStore]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    return Kernel(store), store


@pytest.mark.security
@pytest.mark.invariant("SEC-177")
def test_worker_authored_slack_refs_reconcile_without_browser_secret_exposure(
    monkeypatch,
):
    monkeypatch.setenv("SLACK_INTAKE_SIGNING", "signing-material")
    monkeypatch.setenv("SLACK_SOCKET_APP", "xapp-material")
    monkeypatch.setenv("SLACK_SOCKET_BOT", "xoxb-material")
    kernel, store = _kernel()
    client = TestClient(create_app(kernel))

    response = approved_request(
        client,
        kernel,
        T,
        "POST",
        "/v1/channels",
        headers=ADMIN,
        json={
            "platform": "slack",
            "name": "Support Slack",
            "credential_refs": {
                "signing": "SLACK_INTAKE_SIGNING",
                "app_token": "SLACK_SOCKET_APP",
                "bot_token": "SLACK_SOCKET_BOT",
            },
            "config": {
                "addressing": {"default_target": "cos"},
            },
        },
    )
    assert response.status_code == 201
    channel_id = response.json()["channel"]
    channel = asyncio.run(store.get_channel(T, channel_id))
    assert channel is not None and channel.transport == "socket"

    browser = client.get("/v1/channels", headers=ADMIN)
    assert browser.status_code == 200
    summary = browser.json()["channels"][0]
    assert summary["credential_configured"] is True
    assert summary["gateway"]["status"] == "awaiting_gateway"
    assert "SLACK_" not in browser.text
    assert "material" not in browser.text

    session = client.post(
        "/v1/channels/gateway/session",
        headers=ADMIN,
        json={"channels": [channel_id], "gateway_id": "gateway-test"},
    )
    assert session.status_code == 201
    gateway_headers = {
        "x-boltrig-mcp-token": session.json()["token"],
    }
    desired = client.get(
        "/v1/channels/gateway/reconcile", headers=gateway_headers
    )
    assert desired.status_code == 200
    spec = desired.json()["channels"][0]
    assert spec["state"] == "configured"
    assert spec["secret"] == "signing-material"
    assert spec["config"]["app_token"] == "xapp-material"
    assert spec["config"]["bot_token"] == "xoxb-material"

    heartbeat = client.post(
        "/v1/channels/gateway/heartbeat",
        headers=gateway_headers,
        json={
            "observations": [
                {
                    "channel_id": channel_id,
                    "revision": spec["revision"],
                    "status": "ready",
                }
            ]
        },
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["accepted"] == 1
    observed = client.get("/v1/channels", headers=ADMIN).json()["channels"][0]
    assert observed["gateway"]["status"] == "ready"
    assert observed["gateway"]["desired_revision"] == spec["revision"]
    assert "material" not in str(observed)

    monkeypatch.setenv("SLACK_SOCKET_BOT_V2", "xoxb-rotated")
    rotated = approved_request(
        client,
        kernel,
        T,
        "PATCH",
        f"/v1/channels/{channel_id}",
        headers=ADMIN,
        json={"credential_refs": {"bot_token": "SLACK_SOCKET_BOT_V2"}},
    )
    assert rotated.status_code == 200
    pending = client.get("/v1/channels", headers=ADMIN).json()["channels"][0]
    assert pending["gateway"]["status"] == "awaiting_gateway"
    assert pending["gateway"]["reason_code"] == "desired_state_changed"
    desired_v2 = client.get(
        "/v1/channels/gateway/reconcile", headers=gateway_headers
    ).json()["channels"][0]
    assert desired_v2["revision"] != spec["revision"]
    assert desired_v2["config"]["bot_token"] == "xoxb-rotated"
    assert "SLACK_SOCKET_BOT_V2" not in str(pending)


@pytest.mark.security
@pytest.mark.invariant("SEC-177")
def test_socket_plaintext_secret_is_refused():
    kernel, _ = _kernel()
    client = TestClient(create_app(kernel))
    response = approved_request(
        client,
        kernel,
        T,
        "POST",
        "/v1/channels",
        headers=ADMIN,
        json={
            "platform": "telegram",
            "name": "Unsafe",
            "signing_secret": "plaintext-must-not-persist",
        },
    )
    assert response.status_code in {400, 422}
    assert "plaintext" not in response.text
