"""channel.send is a governed outbound egress verb (decision 0003, SEC-39).

Posting to a channel is high-consequence (HITL by default) and delivers through a
per-transport seam: a socket channel with no direct outbound is queued for the
Phase-2 sidecar. The kernel resolves the channel tenant-scoped and never sends to
an unknown/disabled or cross-tenant one. The optional ``comment`` param is
approver-only: visible in the approval display context, stripped before delivery.
"""

import asyncio
import json

import pytest

from boltrig.adapters.builtin.channel_send import build_channel_send
from boltrig.kernel import Kernel
from boltrig.models import (
    Channel,
    GrantSet,
    InvocationContext,
    PendingHuman,
    TenantPermissions,
)
from boltrig.store import InMemoryStore
from tests.conftest import make_ctx

T = "acme"


@pytest.mark.security
@pytest.mark.invariant("SEC-39")
def test_channel_send_is_high_consequence():
    spec = build_channel_send(InMemoryStore()).describe()[0]
    assert spec.verb_id == "channel.send"
    assert spec.consequence == "high"  # outbound -> HITL by default


@pytest.mark.security
@pytest.mark.invariant("SEC-39")
def test_channel_send_delivers_via_seam_and_is_tenant_scoped():
    async def go():
        store = InMemoryStore()
        await store.upsert_channel(
            Channel(id="ch-1", tenant_id=T, platform="slack", name="Ops", transport="socket")
        )
        sent: list[tuple] = []

        async def deliver(ch, text, target):
            sent.append((ch.id, text, target))
            return {"status": "queued", "transport": ch.transport}

        a = build_channel_send(store, deliver)
        ctx = InvocationContext(tenant_id=T)

        ok = await a.execute(
            "channel.send", {"channel_id": "ch-1", "text": "hi", "target": "C123"}, None, ctx
        )
        assert ok.ok and ok.output["delivery"]["status"] == "queued"
        assert sent == [("ch-1", "hi", "C123")]

        # unknown channel -> failure, nothing delivered
        bad = await a.execute("channel.send", {"channel_id": "nope", "text": "x"}, None, ctx)
        assert not bad.ok

        # a channel from another tenant is invisible (get_channel is tenant-scoped)
        other = InvocationContext(tenant_id="other")
        xt = await a.execute("channel.send", {"channel_id": "ch-1", "text": "x"}, None, other)
        assert not xt.ok
        assert len(sent) == 1  # only the one legitimate send happened

    asyncio.run(go())


@pytest.mark.security
@pytest.mark.invariant("SEC-39")
def test_comment_is_approver_only_and_never_rides_the_outbox():
    async def go():
        store = InMemoryStore()
        store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
        await store.upsert_channel(
            Channel(id="ch-1", tenant_id=T, platform="slack", name="Ops", transport="socket")
        )
        kernel = Kernel(store, blocking_verbs={"channel.send"})
        await kernel.register_adapter(T, build_channel_send(store))
        params = {
            "channel_id": "ch-1",
            "text": "shipping the release now",
            "target": "C123",
            "comment": "approver note: legal signed off, do NOT quote externally",
        }
        ctx = make_ctx(["channel.send"], actor="agent:x")

        # the send pauses; the comment is shown to the approver in the display
        # context (faithful, unredacted - it is FOR the approver)
        with pytest.raises(PendingHuman) as exc:
            await kernel.invoke("channel", "channel.send", params, ctx)
        request = await kernel.hitl.get(T, exc.value.hitl_request_id)
        display = json.loads(request.context)
        assert display["inputs"]["comment"] == params["comment"]
        assert display["inputs"]["text"] == params["text"]

        # the approver clears it and the send executes through the real seam
        await kernel.hitl.answer(T, request.id, "approve", "lead@acme")
        out = await kernel.invoke(
            "channel", "channel.send", params, ctx, approval_id=request.id
        )
        assert out["delivery"]["status"] == "queued"

        # the enqueued outbox row carries ONLY text + target: the comment can
        # never ride the outbox to the channel sender
        (msg,) = await store.claim_channel_outbox(T, ["ch-1"], "test", 60, 20)
        assert set(msg.payload) == {"text", "target"}
        assert msg.payload["text"] == params["text"]
        assert "approver note" not in json.dumps(msg.payload)

    asyncio.run(go())


@pytest.mark.security
@pytest.mark.invariant("SEC-52")
def test_the_manifest_network_posture_binds_the_outbound_webhook_leg(monkeypatch):
    """The outbound_url POST is ordinary egress: an air-gapped (or allow-listed)
    manifest posture must refuse it before anything is put on the wire, not just
    govern web.fetch."""

    async def go():
        monkeypatch.setattr(
            "boltrig.adapters.egress.resolve_host", lambda host: ["93.184.216.34"]
        )
        store = InMemoryStore()
        await store.upsert_channel(
            Channel(
                id="ch-1",
                tenant_id=T,
                platform="webhook",
                name="Ops",
                transport="webhook",
                enabled=True,
                config={"outbound_url": "https://real.example/hook"},
            )
        )
        a = build_channel_send(store, network_config={"air_gapped": True})
        ctx = InvocationContext(tenant_id=T)

        result = await a.execute(
            "channel.send", {"channel_id": "ch-1", "text": "hi"}, None, ctx
        )

        assert not result.ok
        assert result.error is not None
        assert result.error.error_class.value == "invalid"
        assert "air-gapped" in result.error.message

    asyncio.run(go())
