"""The generic-adapter end-to-end proof (decision 0003, Phase 2; SEC-177):
the severed channel gateway, run in-process against a test kernel over an ASGI
transport, drives BOTH links through the reference "custom interface" adapter
(JSON-lines over localhost TCP):

  inbound  - a peer writes one JSON line; the daemon signs it with the
             connect-time secret and POSTs the kernel's ONE intake route; a
             governed work item appears (same path as the webhook class);
  outbound - a row in the kernel's durable outbox is claimed over the
             run-scoped token, delivered to the connected peer, and acked.

This is the mirror test ADDING_A_PLATFORM.md points ports at.
"""

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient  # noqa: F401 - parity with sibling tests

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
SECRET = "roundtripsec_123"

# The gateway is severed (no boltrig imports, SEC-28) - the TEST may straddle
# the boundary: it imports the gateway modules by path and the kernel normally.
_GATEWAY_DIR = str(Path(__file__).resolve().parents[2] / "services" / "channel_gateway")
if _GATEWAY_DIR not in sys.path:
    sys.path.insert(0, _GATEWAY_DIR)

import app as sidecar_app  # noqa: E402


async def _kernel() -> tuple[Kernel, InMemoryStore]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    await store.upsert_channel(
        Channel(id="ch-g1", tenant_id=T, platform="generic", name="Custom",
                transport="socket", credential_ref="cred-1",
                config={"sender_field": "sender"})
    )
    await store.set_credential_ref(T, "cred-1", {"secret": SECRET})
    await store.upsert_channel_binding(
        ChannelBinding(id="b-1", tenant_id=T, channel_id="ch-g1", platform="generic",
                       external_user_id="U-9", subject="alice", role="member")
    )
    return Kernel(store), store


async def _until(predicate, timeout: float = 5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        value = await predicate()
        if value:
            return value
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met within timeout")


@pytest.mark.security
@pytest.mark.invariant("SEC-177")
async def test_generic_adapter_round_trip_against_a_test_kernel():
    kernel, store = await _kernel()
    app = create_app(kernel)
    asgi = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )
    # the run-scoped token, minted through the SAME seam as the session route
    token = kernel.mcp.issue_run_token(
        T, GrantSet(), actor="channel-gateway",
        extra={"channel_gateway": True, "channels": ["ch-g1"]},
    )
    daemon = sidecar_app.ChannelSidecarDaemon(
        sidecar_app.KernelClient("http://test", token, client=asgi),
        [sidecar_app.ChannelSpec(
            channel_id="ch-g1", platform="generic", secret=SECRET,
            config={"listen_host": "127.0.0.1", "listen_port": 0},
        )],
        poll_seconds=0.05,
    )
    await daemon.start()
    try:
        # the adapter comes up under the supervisor; grab its bound port
        adapter = await _until(lambda: _adapter(daemon))
        reader, writer = await asyncio.open_connection("127.0.0.1", adapter.bound_port)

        # --- link (a): one JSON line in -> a governed work item --------------
        writer.write(b'{"id": "m-1", "sender": "U-9", "text": "hello nabu"}\n')
        await writer.drain()
        items = await _until(lambda: _work_items(store))
        (item,) = [w for w in items if w.on_behalf_of == "alice"]
        assert item.raw.get("text") == "hello nabu"
        assert item.target == "cos"  # default addressing, tier-1

        # --- link (b): one outbox row out -> delivered to the peer + acked ---
        await store.enqueue_channel_outbox(
            ChannelOutboxMessage(id="out-1", tenant_id=T, channel_id="ch-g1",
                                 payload={"text": "hi back", "target": "C1"})
        )
        line = await asyncio.wait_for(reader.readline(), timeout=5)
        delivered = json.loads(line.decode("utf-8"))
        assert delivered == {"type": "outbound", "text": "hi back", "target": "C1"}
        # ack settled it: a later claim finds nothing pending for the channel
        await _until(lambda: _settled(store))
        assert await store.claim_channel_outbox(T, ["ch-g1"], "late", 60, 10) == []

        writer.close()
        await writer.wait_closed()
    finally:
        await daemon.stop()
        await asgi.aclose()


async def _adapter(daemon):
    return daemon._adapters.get("ch-g1")


async def _work_items(store):
    return await store.list_work_items(T)


async def _settled(store):
    msg = store._chan_outbox.get((T, "out-1"))
    return msg is not None and msg.status == "delivered"
