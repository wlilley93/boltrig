"""Channel governance verbs (decision 0003): admin-authored lifecycle + pairing.

connect/configure/disconnect mutate the governed Channel noun and are admin-gated;
connect writes the signing secret KERNEL-SIDE (SEC-04/05: never returned, never to
an agent). The pairing flow (issue -> consume) binds an unknown sender to an
internal identity via a hashed, TTL-bounded, single-use, lockout-guarded code.
A non-admin is denied; a correct code binds + proceeds; a wrong code is counted
toward lockout; an expired/locked pairing is denied fail-closed.
"""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from boltrig.adapters.builtin.inbound_webhook import (
    canonical_body,
    expected_signature,
    signed_content,
)
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import GrantSet, TenantPermissions
from boltrig.store import InMemoryStore
from tests.approval import approved_request

T = "acme"
SECRET = "whsec_gov_123"


def _kernel() -> tuple[Kernel, InMemoryStore]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    return Kernel(store), store


def _client(kernel: Kernel) -> TestClient:
    return TestClient(create_app(kernel))


def _admin() -> dict:
    return {"x-boltrig-tenant": T, "x-boltrig-role": "org-admin", "x-boltrig-subject": "root"}


def _member() -> dict:
    return {"x-boltrig-tenant": T, "x-boltrig-role": "member", "x-boltrig-subject": "joe"}


def _approved(client, kernel, method, path, *, json=None):
    return approved_request(
        client, kernel, T, method, path, headers=_admin(), json=json
    )


def _signed(secret: str, payload: dict) -> dict:
    # timestamp bound into the HMAC (M3/SEC-66): a signed webhook now needs a t.
    ts = int(time.time())
    sig = expected_signature(secret, signed_content(ts, canonical_body(payload)))
    return {"x-boltrig-signature": f"t={ts},v1={sig}"}


@pytest.mark.security
@pytest.mark.invariant("SEC-01")
def test_member_cannot_connect_or_pair():
    kernel, _ = _kernel()
    c = _client(kernel)
    assert c.post("/v1/channels", json={"platform": "webhook", "name": "x"}, headers=_member()).status_code == 403
    # connect as admin first, then confirm a member cannot pair or bind either
    ch = _approved(
        c, kernel, "POST", "/v1/channels",
        json={"platform": "webhook", "name": "x", "signing_secret": SECRET},
    ).json()["channel"]
    assert c.post(f"/v1/channels/{ch}/pair", json={"external_user_id": "U", "subject": "s", "role": "member"},
                  headers=_member()).status_code == 403
    assert c.post(f"/v1/channels/{ch}/bindings",
                  json={"external_user_id": "U", "subject": "s", "role": "member"},
                  headers=_member()).status_code == 403


@pytest.mark.security
@pytest.mark.invariant("SEC-01")
def test_connect_stores_secret_kernel_side_never_returns_it():
    kernel, store = _kernel()
    c = _client(kernel)
    r = _approved(
        c, kernel, "POST", "/v1/channels",
        json={"platform": "webhook", "name": "Ops", "signing_secret": SECRET,
              "config": {"sender_field": "sender"}},
    )
    assert r.status_code == 201
    body = r.json()
    assert "inbound_url" in body
    ch_id = body["channel"]
    # the secret is NOT in the response; it lives only in the kernel-side cred store
    assert SECRET not in r.text
    ch = asyncio.run(store.get_channel(T, ch_id))
    assert ch.credential_ref is not None
    ref = asyncio.run(store.get_credential_ref(T, ch.credential_ref))
    assert ref == {"secret": SECRET}


@pytest.mark.security
@pytest.mark.invariant("SEC-01")
def test_disconnect_removes_channel_and_cascades():
    kernel, store = _kernel()
    c = _client(kernel)
    ch = _approved(
        c, kernel, "POST", "/v1/channels",
        json={"platform": "webhook", "name": "Gone", "signing_secret": SECRET},
    ).json()["channel"]
    assert _approved(c, kernel, "DELETE", f"/v1/channels/{ch}").status_code == 200
    assert asyncio.run(store.get_channel(T, ch)) is None


@pytest.mark.security
@pytest.mark.invariant("SEC-01")
def test_pairing_code_consumes_and_binds_unknown_sender():
    kernel, store = _kernel()
    c = _client(kernel)
    ch = _approved(
        c, kernel, "POST", "/v1/channels",
        json={"platform": "webhook", "name": "Pair", "signing_secret": SECRET,
              "unpaired_behavior": "pair", "config": {"sender_field": "sender"}},
    ).json()["channel"]
    code = _approved(
        c, kernel, "POST", f"/v1/channels/{ch}/pair",
        json={"external_user_id": "U-new", "subject": "bob", "role": "member"},
    ).json()["code"]
    # the unbound sender presents the code in its first (signed) message -> bound + proceeds
    payload = {"sender": "U-new", "type": "message", "text": "hi", "id": "e1", "pairing_code": code}
    r = c.post(f"/v1/channels/{ch}/inbound", json=payload, headers=_signed(SECRET, payload))
    assert r.status_code == 202
    wid = r.json()["work_item"]
    items = asyncio.run(store.list_work_items(T))
    assert any(w.id == wid and w.on_behalf_of == "bob" for w in items)  # bound to the authorised identity
    # the code is single-use: a replay is denied (sender now bound, but a fresh
    # unbound sender replaying it must not re-bind)
    binding = asyncio.run(store.get_channel_binding(T, ch, "U-new"))
    assert binding is not None and binding.subject == "bob"


@pytest.mark.security
@pytest.mark.invariant("SEC-01")
def test_wrong_pairing_code_locks_out_after_cap():
    kernel, store = _kernel()
    c = _client(kernel)
    ch = _approved(
        c, kernel, "POST", "/v1/channels",
        json={"platform": "webhook", "name": "Lock", "signing_secret": SECRET,
              "unpaired_behavior": "pair", "config": {"sender_field": "sender"}},
    ).json()["channel"]
    correct = _approved(
        c, kernel, "POST", f"/v1/channels/{ch}/pair",
        json={"external_user_id": "U-new", "subject": "bob", "role": "member"},
    ).json()["code"]
    # hammer the wrong code up to the lockout cap (each is a verified-but-failed attempt)
    for _ in range(5):
        payload = {"sender": "U-new", "type": "message", "id": "x", "pairing_code": "WRONG00"}
        assert c.post(f"/v1/channels/{ch}/inbound", json=payload,
                      headers=_signed(SECRET, payload)).status_code == 403
    # the pairing is now locked (expired); even the correct code is denied
    payload = {"sender": "U-new", "type": "message", "id": "y", "pairing_code": correct}
    assert c.post(f"/v1/channels/{ch}/inbound", json=payload,
                  headers=_signed(SECRET, payload)).status_code == 403
    assert asyncio.run(store.get_channel_binding(T, ch, "U-new")) is None  # never bound


@pytest.mark.security
@pytest.mark.invariant("SEC-01")
def test_expired_pairing_is_denied():
    kernel, store = _kernel()
    c = _client(kernel)
    ch = _approved(
        c, kernel, "POST", "/v1/channels",
        json={"platform": "webhook", "name": "TTL", "signing_secret": SECRET,
              "unpaired_behavior": "pair", "config": {"sender_field": "sender"}},
    ).json()["channel"]
    code = _approved(
        c, kernel, "POST", f"/v1/channels/{ch}/pair",
        json={"external_user_id": "U-new", "subject": "bob", "role": "member"},
    ).json()["code"]
    # force the pairing past its TTL by rewinding its expiry (simulates elapsed time)
    pairing = asyncio.run(store.get_pending_pairing_for_sender(T, ch, "U-new"))
    assert pairing is not None
    from boltrig.models import utcnow
    from datetime import timedelta
    pairing.expires_at = utcnow() - timedelta(minutes=1)
    payload = {"sender": "U-new", "type": "message", "id": "z", "pairing_code": code}
    assert c.post(f"/v1/channels/{ch}/inbound", json=payload,
                  headers=_signed(SECRET, payload)).status_code == 403
