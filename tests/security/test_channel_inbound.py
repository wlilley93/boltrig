"""The webhook-class channel ingress is signature-authenticated, tenant-scoped,
and fail-closed (decision 0003, SEC-01).

A signed inbound event resolves the tenant from the verified channel, maps the
verified sender to a bound Principal, and becomes a governed work-item intake. An
unsigned request is rejected; a verified-but-unbound sender is denied. The tenant
never comes from the payload.
"""

import asyncio
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from boltrig.adapters.builtin import inbound_webhook
from boltrig.adapters.builtin.inbound_webhook import (
    WebhookAuthError,
    canonical_body,
    expected_signature,
    is_duplicate_delivery,
    signed_content,
    verify_and_normalise,
)
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.kernel.channel_routes import INBOUND_RL_PER_SENDER
from boltrig.models import Channel, ChannelBinding, GrantSet, TenantPermissions
from boltrig.store import InMemoryStore, channel_dedup

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
# SEC-01  platform signature headers verify over the RAW request bytes
# --------------------------------------------------------------------------- #
def _raw_and_platform_headers(payload: dict) -> tuple[bytes, dict]:
    # A NON-canonical wire form (insertion order, spaced separators): a
    # signature over it that verifies proves the check ran over the RAW bytes,
    # because the canonical form (sorted keys, tight separators) hashes
    # differently. GitHub-style x-hub-signature-256 = HMAC over exactly this.
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return raw, {"x-hub-signature-256": f"sha256={sig}"}


@pytest.mark.security
@pytest.mark.invariant("SEC-01")
def test_platform_signature_over_raw_bytes_verifies():
    kernel, _ = asyncio.run(_kernel_with_channel())
    payload = {"sender": "U-42", "type": "message", "text": "hello", "id": "evt-raw-1"}
    raw, headers = _raw_and_platform_headers(payload)
    r = _client(kernel).post(
        "/v1/channels/ch-1/inbound",
        content=raw,
        headers={**headers, "content-type": "application/json"},
    )
    assert r.status_code == 202  # the raw-bytes HMAC now verifies end to end


@pytest.mark.security
@pytest.mark.invariant("SEC-01")
def test_boltrig_canonical_scheme_still_verifies_over_noncanonical_wire():
    kernel, _ = asyncio.run(_kernel_with_channel())
    payload = {"sender": "U-42", "type": "message", "text": "hi", "id": "evt-canon-1"}
    # Post NON-canonical bytes while signing the canonical form: the native
    # scheme is defined over the decoded object, so the wire formatting must
    # not matter to it (M3/SEC-66 scheme unchanged by the platform branch).
    r = _client(kernel).post(
        "/v1/channels/ch-1/inbound",
        content=json.dumps(payload).encode("utf-8"),
        headers={**_signed(payload), "content-type": "application/json"},
    )
    assert r.status_code == 202


@pytest.mark.security
@pytest.mark.invariant("SEC-01")
def test_bad_platform_signature_rejected():
    kernel, _ = asyncio.run(_kernel_with_channel())
    payload = {"sender": "U-42", "type": "message", "text": "hello", "id": "evt-raw-2"}
    raw, _headers = _raw_and_platform_headers(payload)
    r = _client(kernel).post(
        "/v1/channels/ch-1/inbound",
        content=raw,
        headers={
            "x-hub-signature-256": "sha256=" + "0" * 64,
            "content-type": "application/json",
        },
    )
    assert r.status_code == 401  # fail closed on mismatch (unchanged behaviour)


@pytest.mark.security
@pytest.mark.invariant("SEC-01")
def test_platform_signature_without_raw_body_fails_closed():
    # The unit seam: a caller that cannot supply the wire bytes must not get a
    # verification against bytes the platform never signed (SEC-01).
    payload = {"sender": "U-42", "type": "message", "id": "evt-raw-3"}
    raw = json.dumps(payload).encode("utf-8")
    sig = hmac.new(SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    with pytest.raises(WebhookAuthError):
        verify_and_normalise(payload, {"x-hub-signature-256": f"sha256={sig}"}, SECRET)


@pytest.mark.security
@pytest.mark.invariant("SEC-66")
def test_stripe_style_platform_signature_binds_timestamp_to_raw_body():
    # Stripe signs t + "." + raw_body; the platform branch must bind the RAW
    # bytes (not the canonical form) into the timestamp-bound content, and the
    # replay window applies over that bound timestamp exactly as it does for
    # the native scheme.
    payload = {"sender": "U-42", "type": "message", "id": "evt-stripe-1"}
    raw = json.dumps(payload).encode("utf-8")
    ts = int(time.time())
    sig = expected_signature(SECRET, signed_content(ts, raw))
    ok = verify_and_normalise(
        payload, {"stripe-signature": f"t={ts},v1={sig}"}, SECRET,
        raw_body=raw, now=float(ts),
    )
    assert ok["authenticated"] is True
    # attack: keep the captured signature, rewrite only the timestamp - the
    # bound raw body makes the reconstruction mismatch (M3/SEC-66)
    with pytest.raises(WebhookAuthError):
        verify_and_normalise(
            payload, {"stripe-signature": f"t={ts + 60},v1={sig}"}, SECRET,
            raw_body=raw, now=float(ts),
        )


# --------------------------------------------------------------------------- #
# SEC-67  inbound intake is rate-limited per channel + per sender (M5)
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-67")
def test_inbound_intake_rate_limited_per_sender(monkeypatch):
    """Flaked once under load (2026-07-30) and the mechanism is now ESTABLISHED:
    the limiter is a FIXED window keyed on ``time.time() // 60``, so when the
    31 requests straddle a minute boundary the count splits across two windows
    and the 31st is accepted. That is the limiter working as designed - a fixed
    window admits up to 2x its limit across a boundary - not a defect, so the
    test pins the clock instead of retrying until the boundary is elsewhere.
    ``InMemoryCounter._now`` exists as exactly this seam."""
    from boltrig.kernel.ratelimit import InMemoryCounter

    monkeypatch.setattr(InMemoryCounter, "_now", lambda self: 1_000_000.0)
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


# --------------------------------------------------------------------------- #
# SEC-175  id-less, unsigned deliveries dedup by CONTENT within a bounded window
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-175")
def test_idless_redelivery_dedupes_by_content():
    inbound_webhook._seen_deliveries.clear()  # isolate the first-tier cache
    store = InMemoryStore()
    # no explicit id, unsigned: no stable delivery id at all, so the content
    # hash fallback synthesises one
    payload = {"sender": "U-42", "type": "message", "text": "hi"}
    first = verify_and_normalise(payload, {}, None, channel_id="ch-1")
    repeat = verify_and_normalise(dict(payload), {}, None, channel_id="ch-1")
    assert first["delivery_id"] is not None
    assert repeat["delivery_id"] == first["delivery_id"]  # same content, same id
    first_seen = asyncio.run(
        is_duplicate_delivery(store, T, "ch-1", first["delivery_id"]))
    repeat_seen = asyncio.run(
        is_duplicate_delivery(store, T, "ch-1", repeat["delivery_id"]))
    assert first_seen is False  # first sighting: ingested
    assert repeat_seen is True  # the identical redelivery in-window: dropped


@pytest.mark.security
@pytest.mark.invariant("SEC-175")
def test_idless_distinct_bodies_are_not_deduped():
    inbound_webhook._seen_deliveries.clear()
    store = InMemoryStore()
    base = {"sender": "U-42", "type": "message", "text": "hi"}
    one = verify_and_normalise(base, {}, None, channel_id="ch-1")
    two = verify_and_normalise({**base, "text": "different"}, {}, None, channel_id="ch-1")
    assert one["delivery_id"] != two["delivery_id"]
    for candidate in (one, two):
        assert asyncio.run(
            is_duplicate_delivery(store, T, "ch-1", candidate["delivery_id"])
        ) is False  # each distinct body is a NEW delivery


@pytest.mark.security
@pytest.mark.invariant("SEC-175")
def test_idless_redelivery_passes_after_the_content_window(monkeypatch):
    inbound_webhook._seen_deliveries.clear()
    store = InMemoryStore()
    # a controllable clock for the STORE tier (the record-and-check authority);
    # the process-local tier takes ``now`` explicitly, the codebase idiom
    clock = datetime(2026, 7, 22, tzinfo=timezone.utc)
    monkeypatch.setattr(channel_dedup, "utcnow", lambda: clock)
    payload = {"sender": "U-42", "type": "message", "text": "hi"}
    did = verify_and_normalise(payload, {}, None, channel_id="ch-1")["delivery_id"]
    t0 = clock.timestamp()
    assert asyncio.run(is_duplicate_delivery(store, T, "ch-1", did, now=t0)) is False
    # inside the window the identical redelivery is a replay - proven against
    # the STORE tier too (local cache cleared, so the store row must answer)
    inbound_webhook._seen_deliveries.clear()
    assert asyncio.run(
        is_duplicate_delivery(store, T, "ch-1", did, now=t0 + 60)) is True
    # ...but once the content window lapses the same body passes as NEW
    later = clock + timedelta(seconds=inbound_webhook._CONTENT_SEEN_TTL_SECONDS + 1)
    monkeypatch.setattr(channel_dedup, "utcnow", lambda: later)
    assert asyncio.run(
        is_duplicate_delivery(store, T, "ch-1", did, now=later.timestamp())) is False


# --------------------------------------------------------------------------- #
# SEC-67  the window boundary behaviour, stated instead of flaking (task #42)
# --------------------------------------------------------------------------- #
@pytest.mark.security
@pytest.mark.invariant("SEC-67")
def test_rate_limit_window_boundary_resets_the_count(monkeypatch):
    """The fixed window's boundary behaviour, pinned as a FACT rather than left
    to surface as a flake: a sender throttled at the end of one window is
    admitted again in the next, which also means a boundary-straddling burst can
    reach up to 2x the limit. That trade-off is the fixed-window design
    (accepted for its Redis-INCR cheapness); this test is what makes the
    boundary crossing a stated property instead of a 1-in-N test failure."""
    from boltrig.kernel.ratelimit import InMemoryCounter, RateLimiter, RateLimited
    from boltrig.kernel.channel_routes import INBOUND_RL_PER_SENDER

    clock = {"now": 1_000_000.0}
    monkeypatch.setattr(InMemoryCounter, "_now", lambda self: clock["now"])
    limiter = RateLimiter(InMemoryCounter())

    async def drive():
        for _ in range(INBOUND_RL_PER_SENDER.max):
            await limiter.enforce(T, "channel.inbound:U-42", INBOUND_RL_PER_SENDER)
        with pytest.raises(RateLimited):
            await limiter.enforce(T, "channel.inbound:U-42", INBOUND_RL_PER_SENDER)
        # the next window: the same sender is admitted again
        clock["now"] += 60.0
        await limiter.enforce(T, "channel.inbound:U-42", INBOUND_RL_PER_SENDER)

    asyncio.run(drive())
