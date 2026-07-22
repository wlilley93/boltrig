"""Channel addressing (decision 0003, Phase 2; SEC-178): an inbound message
carries a TARGET - routing data, never authority. The default is the tier-1
chief of staff ("cos", today's behaviour); a verified sender or the channel's
config mapping can address a named tier-2 subagent/run instead. Identity stays
kernel-authoritative via the binding rows; the work item also carries the
reply route (channel + thread + sender) for round-trip delivery.
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
from boltrig.models import Channel, ChannelBinding, GrantSet, TenantPermissions
from boltrig.store import InMemoryStore

T = "acme"
SECRET = "addrsec_test_123"


async def _kernel(channel_config: dict | None = None) -> tuple[Kernel, InMemoryStore]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    await store.upsert_channel(
        Channel(id="ch-a1", tenant_id=T, platform="slack", name="Ops", transport="socket",
                credential_ref="cred-1",
                config={"sender_field": "sender", **(channel_config or {})})
    )
    await store.set_credential_ref(T, "cred-1", {"secret": SECRET})
    await store.upsert_channel_binding(
        ChannelBinding(id="b-1", tenant_id=T, channel_id="ch-a1", platform="slack",
                       external_user_id="U-9", subject="alice", role="member")
    )
    return Kernel(store), store


def _client(kernel: Kernel) -> TestClient:
    return TestClient(create_app(kernel))


def _signed(payload: dict) -> dict:
    ts = int(time.time())
    sig = expected_signature(SECRET, signed_content(ts, canonical_body(payload)))
    return {"x-boltrig-signature": f"t={ts},v1={sig}"}


def _intake(client: TestClient, n: int, **fields) -> None:
    payload = {"sender": "U-9", "type": "message", "text": "hi", "id": f"evt-{n}", **fields}
    r = client.post("/v1/channels/ch-a1/inbound", json=payload, headers=_signed(payload))
    assert r.status_code == 202, r.text


@pytest.mark.security
@pytest.mark.invariant("SEC-178")
def test_intake_defaults_to_the_tier1_chief_of_staff():
    kernel, store = asyncio.run(_kernel())
    c = _client(kernel)
    _intake(c, 1)
    (item,) = [w for w in asyncio.run(store.list_work_items(T)) if w.on_behalf_of == "alice"]
    # unconfigured channel: the CoS routes it (unchanged pre-Phase-2 behaviour)
    assert item.target == "cos"
    # the reply route is the way BACK: same channel, no thread, the sender
    assert item.reply_route == {"channel_id": "ch-a1", "thread": None, "sender": "U-9"}


@pytest.mark.security
@pytest.mark.invariant("SEC-178")
def test_an_explicit_target_addresses_a_tier2_subagent():
    kernel, store = asyncio.run(_kernel())
    c = _client(kernel)
    _intake(c, 2, target="researcher")
    (item,) = [w for w in asyncio.run(store.list_work_items(T)) if w.on_behalf_of == "alice"]
    assert item.target == "researcher"


@pytest.mark.security
@pytest.mark.invariant("SEC-178")
def test_the_channel_config_maps_a_chat_to_a_target():
    config = {"addressing": {"routes": {"C-ops": "oncall"}, "default_target": "triage"}}
    kernel, store = asyncio.run(_kernel(config))
    c = _client(kernel)
    # a mapped chat addresses its pinned tier-2 target, and the thread is
    # captured on the reply route for the round trip
    _intake(c, 3, chat="C-ops")
    # an unmapped chat falls to the channel's default target
    _intake(c, 4, chat="C-random")
    # an explicit target beats the chat mapping; a malformed one is dropped to it
    _intake(c, 5, chat="C-ops", target="run-42")
    _intake(c, 6, chat="C-ops", target="not a valid slug!")
    items = {w.source_id or w.id: w for w in asyncio.run(store.list_work_items(T))}
    by_delivery = {w.raw.get("id"): w for w in items.values()}
    assert by_delivery["evt-3"].target == "oncall"
    assert by_delivery["evt-3"].reply_route["thread"] == "C-ops"
    assert by_delivery["evt-4"].target == "triage"
    assert by_delivery["evt-5"].target == "run-42"
    assert by_delivery["evt-6"].target == "oncall"
