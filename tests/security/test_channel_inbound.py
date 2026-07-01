"""The webhook-class channel ingress is signature-authenticated, tenant-scoped,
and fail-closed (decision 0003, SEC-01).

A signed inbound event resolves the tenant from the verified channel, maps the
verified sender to a bound Principal, and becomes a governed work-item intake. An
unsigned request is rejected; a verified-but-unbound sender is denied. The tenant
never comes from the payload.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.adapters.builtin.inbound_webhook import canonical_body, expected_signature
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
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
    store.set_credential_ref(T, "cred-1", {"secret": SECRET})
    await store.upsert_channel_binding(
        ChannelBinding(
            id="b-1", tenant_id=T, channel_id="ch-1", platform="webhook",
            external_user_id="U-42", subject="alice", role="member",
        )
    )
    return Kernel(store), store


def _client(kernel: Kernel) -> TestClient:
    return TestClient(create_app(kernel))


def _signed(payload: dict) -> dict:
    return {"x-boltrig-signature": "sha256=" + expected_signature(SECRET, canonical_body(payload))}


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
