"""Self-serve onboarding for customer-facing channels (SEC-180; decision 0003).

A channel whose config opts in (``self_onboard``) binds an unknown VERIFIED
sender itself - at the configured CONSTRAINED role (never above member) and
scope, as a synthetic ``external:<platform>:<id>`` subject with no user record.
The onboarding is a first-class audited event, is rate-limited per channel
before anything is minted, and can enqueue a static welcome to the durable
outbox. OFF by default: a channel without ``self_onboard`` rejects an unpaired
sender exactly as before, and an over-broad config role disables onboarding
fail-closed rather than binding above member.
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
from boltrig.kernel.channel_principal import resolve_channel_principal
from boltrig.models import Channel, ChannelBinding, GrantSet, TenantPermissions, User
from boltrig.store import InMemoryStore

T = "acme"
SECRET = "onboardsec_test_123"


async def _kernel(channel_config: dict | None = None) -> tuple[Kernel, InMemoryStore]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    await store.upsert_channel(
        Channel(id="ch-c1", tenant_id=T, platform="slack", name="Customers",
                transport="socket", credential_ref="cred-1",
                config={"sender_field": "sender", **(channel_config or {})})
    )
    await store.set_credential_ref(T, "cred-1", {"secret": SECRET})
    return Kernel(store), store


def _client(kernel: Kernel) -> TestClient:
    return TestClient(create_app(kernel))


def _signed(payload: dict) -> dict:
    ts = int(time.time())
    sig = expected_signature(SECRET, signed_content(ts, canonical_body(payload)))
    return {"x-boltrig-signature": f"t={ts},v1={sig}"}


def _intake(client: TestClient, sender: str, n: int, *, tag: str = "evt"):
    # delivery ids must be unique across tests in this file: replay dedup keeps a
    # process-local first-tier cache alongside the store authority.
    payload = {"sender": sender, "type": "message", "text": "hi", "id": f"{tag}-{n}"}
    return client.post("/v1/channels/ch-c1/inbound", json=payload, headers=_signed(payload))


@pytest.mark.security
@pytest.mark.invariant("SEC-180")
def test_a_stranger_onboards_at_exactly_the_configured_constrained_role():
    """The onboarded principal's grant ceiling is the member tier's - it operates
    but a self-onboarded customer must NOT get member-tier control verbs
    (``control.*`` is denied), and the synthetic subject carries the configured
    visibility scope. The binding persists and the onboarding is audited
    first-class (who / what platform id / role)."""
    config = {"self_onboard": {"role": "member", "scope": {"departments": ["support"]},
                               "welcome": "Hi! You're in."}}
    kernel, store = asyncio.run(_kernel(config))
    c = _client(kernel)

    r = _intake(c, "U-stranger", 1)
    assert r.status_code == 202, r.text

    (binding,) = asyncio.run(store.list_channel_bindings(T, "ch-c1"))
    assert binding.external_user_id == "U-stranger"
    assert binding.subject == "external:slack:U-stranger"
    assert binding.role == "member"

    principal = asyncio.run(resolve_channel_principal(store, _ch(store), "U-stranger"))
    assert principal is not None
    assert principal.role == "member"
    assert principal.scope == {"departments": ["support"]}
    # the grant ceiling: operates, but NEVER a configure/administer verb
    assert principal.grants.permits("memory.remember") is True
    assert principal.grants.permits("control.channel.connect") is False
    assert principal.grants.permits("control.workflow.trigger") is False

    onboarded = [e for e in asyncio.run(store.audit_query(T))
                 if e.verb == "channel.self_onboard"]
    assert len(onboarded) == 1
    assert onboarded[0].actor == "external:slack:U-stranger"
    assert onboarded[0].detail == {
        "channel": "ch-c1", "platform": "slack",
        "external_user_id": "U-stranger",
        "subject": "external:slack:U-stranger", "role": "member",
    }

    # the configured static welcome rides the durable outbox back to the sender
    outbox = asyncio.run(store.claim_channel_outbox(T, ["ch-c1"], "test", 60, 10))
    assert len(outbox) == 1
    assert outbox[0].payload["text"] == "Hi! You're in."
    assert outbox[0].payload["target"] == "U-stranger"


def _ch(store: InMemoryStore):
    return asyncio.run(store.get_channel_by_id("ch-c1"))


@pytest.mark.security
@pytest.mark.invariant("SEC-180")
def test_onboarding_is_rate_limited_per_channel():
    """The per-channel onboarding throttle trips BEFORE a further binding is
    minted (the intake rate-limit idiom): the 6th stranger in a window is a 429
    and no binding exists for them."""
    kernel, store = asyncio.run(_kernel({"self_onboard": {"role": "member"}}))
    c = _client(kernel)

    for n in range(5):
        r = _intake(c, f"U-{n}", n, tag="rl")
        assert r.status_code == 202, r.text
    r = _intake(c, "U-5", 5, tag="rl")
    assert r.status_code == 429, r.text

    bindings = asyncio.run(store.list_channel_bindings(T, "ch-c1"))
    assert {b.external_user_id for b in bindings} == {f"U-{n}" for n in range(5)}


@pytest.mark.security
@pytest.mark.invariant("SEC-180")
def test_off_by_default_and_an_over_broad_role_never_onboards():
    """A channel WITHOUT self_onboard behaves exactly as today (403), and a
    channel whose config names a role above member (admin) fails closed the
    same way - onboarding is never a path to an elevated tier."""
    # off by default
    kernel, store = asyncio.run(_kernel())
    r = _intake(_client(kernel), "U-stranger", 1, tag="off")
    assert r.status_code == 403, r.text
    assert asyncio.run(store.list_channel_bindings(T, "ch-c1")) == []

    # over-broad config role: onboarding disabled fail-closed
    kernel, store = asyncio.run(_kernel({"self_onboard": {"role": "admin"}}))
    r = _intake(_client(kernel), "U-stranger", 1, tag="broad")
    assert r.status_code == 403, r.text
    assert asyncio.run(store.list_channel_bindings(T, "ch-c1")) == []
    onboarded = [e for e in asyncio.run(store.audit_query(T))
                 if e.verb == "channel.self_onboard"]
    assert onboarded == []


@pytest.mark.security
@pytest.mark.invariant("SEC-180")
def test_an_existing_binding_is_never_onboarded_over():
    """A sender whose binding EXISTS but resolves to no principal (here: a
    deactivated user) is not self-onboarded into a fresh synthetic identity -
    onboarding must never resurrect a revoked sender or clobber a binding."""
    kernel, store = asyncio.run(_kernel({"self_onboard": {"role": "member"}}))
    asyncio.run(store.upsert_user(User(
        id="ex-employee", tenant_id=T, email="ex@example.com", role="member",
        scope={"all": True}, status="deactivated",
    )))
    asyncio.run(store.upsert_channel_binding(ChannelBinding(
        id="b-ex", tenant_id=T, channel_id="ch-c1", platform="slack",
        external_user_id="U-ex", subject="ex-employee", role="member",
    )))

    r = _intake(_client(kernel), "U-ex", 1, tag="deact")
    assert r.status_code == 403, r.text

    (binding,) = asyncio.run(store.list_channel_bindings(T, "ch-c1"))
    assert binding.subject == "ex-employee"  # untouched - no synthetic re-onboard
    onboarded = [e for e in asyncio.run(store.audit_query(T))
                 if e.verb == "channel.self_onboard"]
    assert onboarded == []
