"""The webhook-class channel ingress is signature-authenticated, tenant-scoped,
and fail-closed (decision 0003, SEC-01).

A signed inbound event resolves the tenant from the verified channel, maps the
verified sender to a bound Principal, and becomes a governed work-item intake. An
unsigned request is rejected; a verified-but-unbound sender is denied. The tenant
never comes from the payload.
"""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from boltrig.adapters.builtin import inbound_webhook
from boltrig.adapters.builtin.inbound_webhook import (
    WebhookAuthError,
    canonical_body,
    expected_signature,
    signed_content,
    verify_and_normalise,
)
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.kernel.channel_routes import INBOUND_RL_PER_SENDER
from boltrig.models import Channel, ChannelBinding, GrantSet, TenantPermissions
from boltrig.store import InMemoryStore

T = "acme"
SECRET = "whsec_test_123"


async def _kernel_with_channel() -> tuple[Kernel, InMemoryStore]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    await store.upsert_channel(
        Channel(
            id="ch-1", tenant_id=T, platform="webhook", name="Ops", transport="webhook",
            credential_ref="cred-1", config={"sender_field": "sender"},
        )
    )
    await store.set_credential_ref(T, "cred-1", {"secret": SECRET})
    await store.upsert_channel_binding(
        ChannelBinding(
            id="b-1", tenant_id=T, channel_id="ch-1", platform="webhook",
            external_user_id="U-42", subject="alice", role="member",
        )
    )
    return Kernel(store), store


def _client(kernel: Kernel) -> TestClient:
    return TestClient(create_app(kernel))


def _signed(payload: dict, ts: int | None = None) -> dict:
    # Stripe-style t=,v1= header: the timestamp is bound into the signed bytes so
    # it cannot be rewritten to defeat the replay window (M3/SEC-66).
    ts = ts if ts is not None else int(time.time())
    sig = expected_signature(SECRET, signed_content(ts, canonical_body(payload)))
    return {"x-boltrig-signature": f"t={ts},v1={sig}"}


@pytest.mark.security
@pytest.mark.invariant("SEC-01")
def test_signed_inbound_creates_governed_work_item():
    kernel, store = asyncio.run(_kernel_with_channel())
    payload = {"sender": "U-42", "type": "message", "text": "hello", "id": "evt-1"}
    r = _client(kernel).post("/v1/channels/ch-1/inbound", json=payload, headers=_signed(payload))
    assert r.status_code == 202
    wid = r.json()["work_item"]
    items = asyncio.run(store.list_work_items(T))
    # the intake is attributed to the bound INTERNAL identity, not the raw sender
    assert any(w.id == wid and w.on_behalf_of == "alice" for w in items)


@pytest.mark.security
@pytest.mark.invariant("SEC-01")
def test_unsigned_inbound_rejected():
    kernel, _ = asyncio.run(_kernel_with_channel())
    r = _client(kernel).post("/v1/channels/ch-1/inbound", json={"sender": "U-42", "type": "x"})
    assert r.status_code == 401  # a signed channel with no signature -> denied


@pytest.mark.security
@pytest.mark.invariant("SEC-01")
def test_verified_but_unbound_sender_denied():
    kernel, _ = asyncio.run(_kernel_with_channel())
    payload = {"sender": "U-stranger", "type": "message", "id": "evt-2"}
    r = _client(kernel).post("/v1/channels/ch-1/inbound", json=payload, headers=_signed(payload))
    assert r.status_code == 403  # valid signature, but the sender is not paired (fail-closed)


@pytest.mark.security
@pytest.mark.invariant("SEC-01")
def test_unknown_channel_404():
    kernel, _ = asyncio.run(_kernel_with_channel())
    r = _client(kernel).post("/v1/channels/nope/inbound", json={"sender": "U-42"})
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# SEC-66  webhook replay: timestamp is bound into the HMAC + delivery dedup (M3)
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-66")
def test_webhook_replay_with_rewritten_timestamp_rejected():
    # A genuine (payload, signature) pair signed at t0. Because t is bound into the
    # signed content, an attacker who captured it cannot move the timestamp forward
    # to slip past the replay window: rewriting t makes the signature reconstruct
    # differently and the compare fails. Without the fix (body-only HMAC) the
    # rewritten-timestamp request would verify, and this test would not raise.
    payload = {"type": "message", "id": "evt-r1", "sender": "U-42"}
    t0 = int(time.time()) - 10
    sig = expected_signature(SECRET, signed_content(t0, canonical_body(payload)))
    now = int(time.time())
    # honest control: the correctly-bound timestamp verifies within the window
    ok = verify_and_normalise(
        payload, {"x-boltrig-signature": f"t={t0},v1={sig}"}, SECRET, now=now
    )
    assert ok["authenticated"] is True
    # attack: keep the captured signature, rewrite only the timestamp to "now"
    with pytest.raises(WebhookAuthError):
        verify_and_normalise(
            payload, {"x-boltrig-signature": f"t={now},v1={sig}"}, SECRET, now=now
        )


@pytest.mark.security
@pytest.mark.invariant("SEC-66")
def test_duplicate_delivery_not_double_ingested():
    inbound_webhook._seen_deliveries.clear()  # process-local seen-set (isolate the test)
    kernel, store = asyncio.run(_kernel_with_channel())
    client = _client(kernel)
    payload = {"sender": "U-42", "type": "message", "text": "hi", "id": "evt-dup-1"}
    headers = _signed(payload)
    first = client.post("/v1/channels/ch-1/inbound", json=payload, headers=headers)
    assert first.status_code == 202
    # replay the exact same signed request (a genuine, non-forged signature)
    second = client.post("/v1/channels/ch-1/inbound", json=payload, headers=headers)
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    # exactly one work item exists, not two
    items = asyncio.run(store.list_work_items(T))
    assert sum(1 for w in items if w.on_behalf_of == "alice") == 1


# --------------------------------------------------------------------------- #
# SEC-67  inbound intake is rate-limited per channel + per sender (M5)
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-67")
def test_inbound_intake_rate_limited_per_sender():
    inbound_webhook._seen_deliveries.clear()
    kernel, store = asyncio.run(_kernel_with_channel())
    client = _client(kernel)
    limit = INBOUND_RL_PER_SENDER.max
    # each request carries a unique id (so dedup never masks the rate limit)
    accepted = 0
    for i in range(limit):
        payload = {"sender": "U-42", "type": "message", "id": f"rl-{i}"}
        r = client.post("/v1/channels/ch-1/inbound", json=payload, headers=_signed(payload))
        assert r.status_code == 202
        accepted += 1
    # the N+1th rapid inbound from the same sender is throttled
    over = {"sender": "U-42", "type": "message", "id": f"rl-{limit}"}
    r = client.post("/v1/channels/ch-1/inbound", json=over, headers=_signed(over))
    assert r.status_code == 429
    assert r.json()["status"] == "throttled"
    # no extra work item was created past the limit
    items = asyncio.run(store.list_work_items(T))
    assert sum(1 for w in items if w.on_behalf_of == "alice") == accepted == limit
