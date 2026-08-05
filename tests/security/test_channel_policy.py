"""Opt-in channel boundary policy (allowlisted chats and thread grant ceilings)."""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from boltrig.adapters.builtin.inbound_webhook import canonical_body, expected_signature, signed_content
from boltrig.fleet.authority import context_for
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.kernel.channel_policy import chat_is_allowed, thread_ceiling
from boltrig.models import Channel, ChannelBinding, GrantSet, TenantPermissions, User
from boltrig.store import InMemoryStore

T = "policy-tenant"
SECRET = "policy-secret"


def _signed(payload: dict) -> dict:
    ts = int(time.time())
    sig = expected_signature(SECRET, signed_content(ts, canonical_body(payload)))
    return {"x-boltrig-signature": f"t={ts},v1={sig}"}


def _kernel(config: dict) -> tuple[Kernel, InMemoryStore]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    asyncio.run(store.upsert_channel(
        Channel(id="ch-policy", tenant_id=T, platform="slack", name="Policy",
                transport="webhook", credential_ref="cred", config={"sender_field": "sender", **config})
    ))
    asyncio.run(store.set_credential_ref(T, "cred", {"secret": SECRET}))
    asyncio.run(store.upsert_channel_binding(
        ChannelBinding(id="binding", tenant_id=T, channel_id="ch-policy", platform="slack",
                       external_user_id="U-1", subject="alice", role="member")
    ))
    return Kernel(store), store


def _client(kernel: Kernel) -> TestClient:
    return TestClient(create_app(kernel))


def _post(client: TestClient, n: int, **extra):
    payload = {"sender": "U-1", "type": "message", "text": "hi", "id": f"policy-{n}", **extra}
    return client.post("/v1/channels/ch-policy/inbound", json=payload, headers=_signed(payload))


@pytest.mark.security
@pytest.mark.invariant("SEC-195")
def test_allowed_chats_are_opt_in_and_fail_closed_for_unknown_or_missing_chat():
    kernel, store = _kernel({"allowed_chats": ["C-ops"]})
    client = _client(kernel)

    assert _post(client, 1, chat="C-ops").status_code == 202
    denied = _post(client, 2, chat="C-random")
    assert denied.status_code == 403
    assert denied.json() == {"status": "denied", "reason": "chat_not_allowed"}
    assert _post(client, 3).status_code == 403
    assert len(asyncio.run(store.list_work_items(T))) == 1


@pytest.mark.security
@pytest.mark.invariant("SEC-195")
def test_malformed_allowlist_or_ceiling_never_falls_open():
    kernel, _ = _kernel({"allowed_chats": "C-ops"})
    channel = asyncio.run(kernel.store.get_channel(T, "ch-policy"))
    assert channel is not None
    assert not chat_is_allowed(channel, {"chat": "C-ops"})
    channel.config = {"thread_ceilings": {"C-ops": {"allow": "job.one"}}}
    ceiling = thread_ceiling(channel, "C-ops")
    assert ceiling is not None
    assert not ceiling.permits("job.one")


@pytest.mark.security
@pytest.mark.invariant("SEC-195")
def test_thread_ceiling_is_stamped_and_narrows_execution_authority():
    kernel, store = _kernel({"thread_ceilings": {"C-ops": {"allow": ["job.one"]}}})
    asyncio.run(store.upsert_user(
        User(id="alice", tenant_id=T, email="alice@example.test", role="member",
             scope={"verbs": ["job.one", "job.two"]}, status="active")
    ))
    client = _client(kernel)
    response = _post(client, 4, chat="C-ops")
    assert response.status_code == 202, response.text
    item = asyncio.run(store.get_work_item(T, response.json()["work_item"]))
    assert item is not None
    assert item.constraints["_channel_thread_ceiling"] == {
        "thread": "C-ops", "allow": ["job.one"], "deny": []
    }
    context = asyncio.run(context_for(store, item, item.id))
    assert context.grants.permits("job.one")
    assert not context.grants.permits("job.two")
