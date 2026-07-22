"""The WhatsApp (Baileys bridge) adapter end-to-end proof (decision 0003,
item 7 of the platform plan; SEC-177) - the mirror of
test_channel_slack_roundtrip.py for the second platform port: the severed
gateway, run in-process against a test kernel over an ASGI transport, drives
BOTH links through the WhatsApp adapter against a FAKE bridge (no network, no
Node):

  the real bridge is a Node/Baileys process (services/channel_gateway/
  whatsapp_bridge/) and cannot run in this suite - the fake below serves the
  SAME loopback HTTP contract the adapted bridge.js implements: inbound push
  ``POST {adapter}/inbound {"messageId","chatId","senderId","isGroup","body"}``
  and outbound ``POST {bridge}/send {"chatId","message"} -> {"success": true,
  "messageId"}``;

  inbound  - one DM event becomes a governed work item via the ONE signed
             intake route, the phone-number sender resolving through the
             binding row and the chat JID landing on the reply route as the
             thread; one GROUP event rides the same path with the group JID
             as its thread (sender = the participant JID user part); an event
             with no messageId is refused (400) and never ingested;
  outbound - one outbox row is claimed over the run-scoped token, delivered
             via the bridge /send with the right body (target = the chat
             JID), and acked.
"""

import asyncio
import sys
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

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
SECRET = "whatsaproundtrip_123"
PHONE_JID = "34655501001@s.whatsapp.net"
GROUP_JID = "120363001234@g.us"

# The gateway is severed (no boltrig imports, SEC-28) - the TEST may straddle
# the boundary: it imports the gateway modules by path and the kernel normally.
_GATEWAY_DIR = str(Path(__file__).resolve().parents[2] / "services" / "channel_gateway")
if _GATEWAY_DIR not in sys.path:
    sys.path.insert(0, _GATEWAY_DIR)

import app as sidecar_app  # noqa: E402
import whatsapp_adapter  # noqa: E402,F401  (registers the "whatsapp" platform)


async def _kernel() -> tuple[Kernel, InMemoryStore]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    await store.upsert_channel(
        Channel(id="ch-w1", tenant_id=T, platform="whatsapp", name="WhatsApp",
                transport="socket", credential_ref="cred-1",
                config={"sender_field": "sender"})
    )
    await store.set_credential_ref(T, "cred-1", {"secret": SECRET})
    await store.upsert_channel_binding(
        ChannelBinding(id="b-1", tenant_id=T, channel_id="ch-w1", platform="whatsapp",
                       external_user_id="34655501001", subject="alice", role="member")
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


async def _serve(app: FastAPI) -> tuple[uvicorn.Server, asyncio.Task, int]:
    """Run a tiny ASGI app on an ephemeral loopback port (the fake bridge)."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    task = asyncio.create_task(server.serve())
    for _ in range(500):
        if server.started:
            break
        await asyncio.sleep(0.01)
    assert server.started, "fake bridge did not come up"
    port = int(server.servers[0].sockets[0].getsockname()[1])
    return server, task, port


@pytest.mark.security
@pytest.mark.invariant("SEC-177")
async def test_whatsapp_adapter_round_trip_against_a_test_kernel():
    kernel, store = await _kernel()
    kernel_app = create_app(kernel)
    asgi = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=kernel_app), base_url="http://test"
    )

    # --- the fake bridge (the same HTTP contract as bridge.js) -------------
    sent: list[dict] = []  # /send bodies the adapter posted

    fake = FastAPI(title="fake whatsapp bridge")

    @fake.post("/send")
    async def _send(request: Request) -> JSONResponse:
        body = await request.json()
        if not body.get("chatId") or not body.get("message"):
            return JSONResponse({"error": "chatId and message are required"}, status_code=400)
        sent.append(body)
        return JSONResponse({"success": True, "messageId": "WAMID.fake.1", "messageIds": ["WAMID.fake.1"]})

    @fake.get("/health")
    async def _health() -> JSONResponse:
        return JSONResponse({"status": "connected", "uptime": 1.0})

    bridge_server, bridge_task, bridge_port = await _serve(fake)

    token = kernel.mcp.issue_run_token(
        T, GrantSet(), actor="channel-gateway",
        extra={"channel_gateway": True, "channels": ["ch-w1"]},
    )
    daemon = sidecar_app.ChannelSidecarDaemon(
        sidecar_app.KernelClient("http://test", token, client=asgi),
        [sidecar_app.ChannelSpec(
            channel_id="ch-w1", platform="whatsapp", secret=SECRET,
            config={
                "bridge_base": f"http://127.0.0.1:{bridge_port}",
                "listen_port": 0,
                "egress_allow": ["127.0.0.1"],
            },
        )],
        poll_seconds=0.05,
    )
    await daemon.start()
    try:
        # the adapter comes up under the supervisor and binds its listener
        adapter = await _until(lambda: _adapter(daemon))
        inbound_url = f"http://127.0.0.1:{adapter.bound_port}/inbound"
        pusher = httpx.AsyncClient()  # the test plays the bridge's push side
        try:
            # --- link (a): one DM event in -> a governed work item ----------
            resp = await pusher.post(inbound_url, json={
                "messageId": "ABCD-EFGH-1", "chatId": PHONE_JID,
                "senderId": PHONE_JID, "isGroup": False, "body": "hello nabu",
            })
            assert resp.status_code == 200 and resp.json()["ok"]
            items = await _until(lambda: _work_items(store))
            (item,) = [w for w in items if w.on_behalf_of == "alice"]
            assert item.raw.get("text") == "hello nabu"
            assert item.target == "cos"  # default addressing, tier-1
            assert item.reply_route["thread"] == PHONE_JID  # the way back

            # a group event: sender from the participant JID, group JID as thread
            resp = await pusher.post(inbound_url, json={
                "messageId": "ABCD-EFGH-2", "chatId": GROUP_JID,
                "senderId": PHONE_JID, "isGroup": True, "body": "group hi",
            })
            assert resp.status_code == 200
            await _until(lambda: _two_items(store))
            group_item = [w for w in await store.list_work_items(T)
                          if w.raw.get("text") == "group hi"][0]
            assert group_item.on_behalf_of == "alice"
            assert group_item.reply_route["thread"] == GROUP_JID

            # an event with no stable delivery id is refused, never ingested
            resp = await pusher.post(inbound_url, json={
                "chatId": PHONE_JID, "senderId": PHONE_JID,
                "isGroup": False, "body": "id-less",
            })
            assert resp.status_code == 400
            await asyncio.sleep(0.3)
            assert len(await store.list_work_items(T)) == 2

            # --- link (b): one outbox row out -> bridge /send + acked --------
            await store.enqueue_channel_outbox(
                ChannelOutboxMessage(id="out-w1", tenant_id=T, channel_id="ch-w1",
                                     payload={"text": "hi back", "target": PHONE_JID})
            )
            (delivery,) = await _until(lambda: _delivered(sent))
            assert delivery == {"chatId": PHONE_JID, "message": "hi back"}
            await _until(lambda: _settled(store))
            assert await store.claim_channel_outbox(T, ["ch-w1"], "late", 60, 10) == []
        finally:
            await pusher.aclose()
    finally:
        await daemon.stop()
        await asgi.aclose()
        bridge_server.should_exit = True
        await bridge_task


async def _adapter(daemon):
    return daemon._adapters.get("ch-w1")


async def _work_items(store):
    return await store.list_work_items(T)


async def _two_items(store):
    items = await store.list_work_items(T)
    return items if len(items) >= 2 else None


async def _delivered(sent):
    return sent or None


async def _settled(store):
    msg = store._chan_outbox.get((T, "out-w1"))
    return msg is not None and msg.status == "delivered"
