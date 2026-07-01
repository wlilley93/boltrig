"""channel.send is a governed outbound egress verb (decision 0003, SEC-39).

Posting to a channel is high-consequence (HITL by default) and delivers through a
per-transport seam: a socket channel with no direct outbound is queued for the
Phase-2 sidecar. The kernel resolves the channel tenant-scoped and never sends to
an unknown/disabled or cross-tenant one.
"""

import asyncio

import pytest

from boltrig.adapters.builtin.channel_send import build_channel_send
from boltrig.models import Channel, InvocationContext
from boltrig.store import InMemoryStore

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
