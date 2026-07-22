"""The channel gateway's kernel links (decision 0003, Phase 2): the session
mint is admin-gated, the outbox links are run-scoped-token-gated, and a
socket-class intake terminates at the ONE signed intake route.

The token comes from the SAME seam as the MCP face (McpFace.issue_run_token):
a missing/garbage/non-gateway token is refused; the token's channel set bounds
what may be claimed; its lease id is the claim worker id. Socket intake reuses
the webhook-class HMAC path end to end, including the durable replay dedup.
"""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from boltrig.adapters.builtin import inbound_webhook
from boltrig.adapters.builtin.inbound_webhook import (
    canonical_body,
    expected_signature,
    signed_content,
)
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import (
    Channel,
    ChannelBinding,
    ChannelOutboxMessage,
    GrantSet,
    TenantPermissions,
)
from boltrig.store import InMemoryStore

T = "acme"
SECRET = "socksec_test_123"


async def _kernel() -> tuple[Kernel, InMemoryStore]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    await store.upsert_channel(
        Channel(id="ch-s1", tenant_id=T, platform="slack", name="Ops", transport="socket",
                credential_ref="cred-1", config={"sender_field": "sender"})
    )
    await store.upsert_channel(
        Channel(id="ch-s2", tenant_id=T, platform="discord", name="Chat", transport="socket")
    )
    await store.upsert_channel(
        Channel(id="ch-w1", tenant_id=T, platform="webhook", name="Hook", transport="webhook")
    )
    await store.set_credential_ref(T, "cred-1", {"secret": SECRET})
    await store.upsert_channel_binding(
        ChannelBinding(id="b-1", tenant_id=T, channel_id="ch-s1", platform="slack",
                       external_user_id="U-9", subject="alice", role="member")
    )
    return Kernel(store), store


def _client(kernel: Kernel) -> TestClient:
    return TestClient(create_app(kernel))


def _admin() -> dict:
    return {"x-boltrig-tenant": T, "x-boltrig-role": "org-admin", "x-boltrig-subject": "root"}


def _member() -> dict:
    return {"x-boltrig-tenant": T, "x-boltrig-role": "member", "x-boltrig-subject": "joe"}


def _signed(payload: dict) -> dict:
    ts = int(time.time())
    sig = expected_signature(SECRET, signed_content(ts, canonical_body(payload)))
    return {"x-boltrig-signature": f"t={ts},v1={sig}"}


def _session(client: TestClient, channels: list[str]) -> str:
    r = client.post("/v1/channels/gateway/session", json={"channels": channels},
                    headers=_admin())
    assert r.status_code == 201, r.text
    return r.json()["token"]


# --- the session mint ---------------------------------------------------------
@pytest.mark.security
@pytest.mark.invariant("SEC-177")
def test_session_mint_is_admin_gated_and_socket_only():
    kernel, _ = asyncio.run(_kernel())
    c = _client(kernel)
    assert c.post("/v1/channels/gateway/session", json={"channels": ["ch-s1"]},
                  headers=_member()).status_code == 403
    # a webhook-class channel cannot take a gateway session
    assert c.post("/v1/channels/gateway/session", json={"channels": ["ch-w1"]},
                  headers=_admin()).status_code == 400
    # an unknown / cross-tenant channel is refused
    assert c.post("/v1/channels/gateway/session", json={"channels": ["nope"]},
                  headers=_admin()).status_code == 400
    # an out-of-bounds TTL is refused by the run-token seam's own clamp
    assert c.post("/v1/channels/gateway/session",
                  json={"channels": ["ch-s1"], "ttl_seconds": 99999},
                  headers=_admin()).status_code == 400
    r = c.post("/v1/channels/gateway/session", json={"channels": ["ch-s1"]},
               headers=_admin())
    assert r.status_code == 201
    assert r.json()["token"] and r.json()["channels"] == ["ch-s1"]


# --- the outbox links ---------------------------------------------------------
@pytest.mark.security
@pytest.mark.invariant("SEC-177")
def test_outbox_links_require_a_sidecar_run_token():
    kernel, store = asyncio.run(_kernel())
    c = _client(kernel)
    asyncio.run(store.enqueue_channel_outbox(
        ChannelOutboxMessage(id="m-1", tenant_id=T, channel_id="ch-s1",
                             payload={"text": "hi", "target": "C1"})
    ))
    # no token / garbage token -> 401
    assert c.post("/v1/channels/gateway/outbox/claim", json={}).status_code == 401
    assert c.post("/v1/channels/gateway/outbox/claim", json={},
                  headers={"x-boltrig-mcp-token": "garbage"}).status_code == 401
    # a live run token that is NOT a gateway session -> 401
    plain = kernel.mcp.issue_run_token(T, GrantSet.of(["*"]))
    assert c.post("/v1/channels/gateway/outbox/claim", json={},
                  headers={"x-boltrig-mcp-token": plain}).status_code == 401


@pytest.mark.security
@pytest.mark.invariant("SEC-177")
def test_outbox_claim_ack_fail_over_the_sidecar_token():
    kernel, store = asyncio.run(_kernel())
    c = _client(kernel)
    token = _session(c, ["ch-s1"])
    H = {"x-boltrig-mcp-token": token}
    asyncio.run(store.enqueue_channel_outbox(
        ChannelOutboxMessage(id="m-1", tenant_id=T, channel_id="ch-s1",
                             payload={"text": "hi", "target": "C1"})
    ))
    asyncio.run(store.enqueue_channel_outbox(
        ChannelOutboxMessage(id="m-2", tenant_id=T, channel_id="ch-s2",
                             payload={"text": "off-limits", "target": "C2"})
    ))
    # the claim is bounded to the token's channel set: ch-s2's row never leaves
    r = c.post("/v1/channels/gateway/outbox/claim", json={}, headers=H)
    assert r.status_code == 200
    assert [(m["id"], m["channel_id"]) for m in r.json()["messages"]] == [("m-1", "ch-s1")]
    # a second claim by the same token wins nothing while the lease is live
    assert c.post("/v1/channels/gateway/outbox/claim", json={}, headers=H).json()["messages"] == []
    # ack settles it; a repeat ack is a conflict (the claim is spent)
    assert c.post("/v1/channels/gateway/outbox/m-1/ack", headers=H).status_code == 200
    assert c.post("/v1/channels/gateway/outbox/m-1/ack", headers=H).status_code == 409
    # fail on an unclaimed row is likewise a conflict
    assert c.post("/v1/channels/gateway/outbox/m-2/fail", json={"error": "x"},
                  headers=H).status_code == 409
    # a revoked token stops working at once (the MCP seam's revoke)
    kernel.mcp.revoke(token)
    assert c.post("/v1/channels/gateway/outbox/claim", json={}, headers=H).status_code == 401


# --- socket intake shares the ONE path ----------------------------------------
@pytest.mark.security
@pytest.mark.invariant("SEC-177")
def test_socket_intake_uses_the_one_signed_route_with_durable_dedup():
    inbound_webhook._seen_deliveries.clear()  # isolate the first-tier cache
    kernel, store = asyncio.run(_kernel())
    c = _client(kernel)
    payload = {"sender": "U-9", "type": "message", "text": "hello", "id": "evt-s1"}
    first = c.post("/v1/channels/ch-s1/inbound", json=payload, headers=_signed(payload))
    assert first.status_code == 202
    # DURABLE proof: wipe the process-local cache tier entirely; the replay is
    # still refused, so the store row - not process memory - is the authority.
    inbound_webhook._seen_deliveries.clear()
    second = c.post("/v1/channels/ch-s1/inbound", json=payload, headers=_signed(payload))
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    items = asyncio.run(store.list_work_items(T))
    assert sum(1 for w in items if w.on_behalf_of == "alice") == 1
    # an unsigned socket intake is denied exactly like the webhook class
    assert c.post("/v1/channels/ch-s1/inbound",
                  json={"sender": "U-9", "id": "evt-s2"}).status_code == 401
