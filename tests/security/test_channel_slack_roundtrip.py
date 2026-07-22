"""The Slack Socket Mode adapter end-to-end proof (decision 0003, Phase 2;
SEC-177) - the mirror of test_channel_gateway_roundtrip.py for the REFERENCE
platform port (ADDING_A_PLATFORM.md): the severed gateway, run in-process
against a test kernel over an ASGI transport, drives BOTH links through the
Slack adapter against a FAKE Slack (no network):

  fake Slack API (httpx MockTransport) - apps.connections.open returns the
  fake Socket Mode URL; chat.postMessage records what deliver() posted;
  fake Socket Mode server (websockets) - the adapter connects, acks every
  envelope by id, and normalises events_api envelopes;

  inbound  - one threaded message event becomes a governed work item via the
             ONE signed intake route, its thread_ts landing on the reply route;
             a bot-self event and a message_changed subtype are acked but
             ignored;
  outbound - one outbox row is claimed over the run-scoped token, delivered
             via chat.postMessage with the right body (channel:thread_ts
             target split), and acked.
"""

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest
import websockets

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
SECRET = "slackroundtrip_123"
THREAD_TS = "1720000000.000100"

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
        Channel(id="ch-s1", tenant_id=T, platform="slack", name="Slack",
                transport="socket", credential_ref="cred-1",
                config={"sender_field": "sender"})
    )
    await store.set_credential_ref(T, "cred-1", {"secret": SECRET})
    await store.upsert_channel_binding(
        ChannelBinding(id="b-1", tenant_id=T, channel_id="ch-s1", platform="slack",
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


def _envelope(envelope_id: str, event_id: str, event: dict) -> str:
    return json.dumps({
        "envelope_id": envelope_id, "type": "events_api",
        "payload": {"event_id": event_id, "event": event},
    })


@pytest.mark.security
@pytest.mark.invariant("SEC-177")
async def test_slack_adapter_round_trip_against_a_test_kernel():
    kernel, store = await _kernel()
    kernel_app = create_app(kernel)
    asgi = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=kernel_app), base_url="http://test"
    )

    # --- the fake Slack -----------------------------------------------------
    sockets: asyncio.Queue = asyncio.Queue()   # accepted Socket Mode conns
    acks: asyncio.Queue = asyncio.Queue()      # envelope ids the adapter acked
    posted: list[dict] = []                    # chat.postMessage bodies + auth

    async def _socket_handler(ws):
        await sockets.put(ws)
        try:
            async for raw in ws:
                message = json.loads(raw)
                if set(message) == {"envelope_id"}:  # an ack frame
                    await acks.put(message["envelope_id"])
        except websockets.ConnectionClosed:
            pass

    socket_server = await websockets.serve(_socket_handler, "127.0.0.1", 0)
    socket_port = socket_server.sockets[0].getsockname()[1]

    def _slack_api(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/apps.connections.open"):
            return httpx.Response(
                200, json={"ok": True, "url": f"ws://127.0.0.1:{socket_port}/"}
            )
        if request.url.path.endswith("/chat.postMessage"):
            posted.append({
                "auth": request.headers.get("authorization"),
                **json.loads(request.content),
            })
            return httpx.Response(200, json={"ok": True, "ts": "1720000001.000001"})
        return httpx.Response(404, json={"ok": False, "error": "unknown_method"})

    fake_api = httpx.AsyncClient(transport=httpx.MockTransport(_slack_api))

    token = kernel.mcp.issue_run_token(
        T, GrantSet(), actor="channel-gateway",
        extra={"channel_gateway": True, "channels": ["ch-s1"]},
    )
    daemon = sidecar_app.ChannelSidecarDaemon(
        sidecar_app.KernelClient("http://test", token, client=asgi),
        [sidecar_app.ChannelSpec(
            channel_id="ch-s1", platform="slack", secret=SECRET,
            config={
                "app_token": "xapp-test-token",
                "bot_token": "xoxb-test-token",
                "api_base": "http://127.0.0.1/api",
                "egress_allow": ["127.0.0.1"],
                "http_client": fake_api,
            },
        )],
        poll_seconds=0.05,
    )
    await daemon.start()
    try:
        # the adapter comes up under the supervisor and opens the socket
        ws = await asyncio.wait_for(sockets.get(), timeout=5)

        # --- link (a): one threaded event in -> a governed work item --------
        await ws.send(_envelope("env-1", "Ev0001", {
            "type": "message", "user": "U-9", "text": "hello nabu",
            "channel": "C123", "ts": "1720000000.000200", "thread_ts": THREAD_TS,
        }))
        assert await asyncio.wait_for(acks.get(), timeout=5) == "env-1"
        items = await _until(lambda: _work_items(store))
        (item,) = [w for w in items if w.on_behalf_of == "alice"]
        assert item.raw.get("text") == "hello nabu"
        assert item.target == "cos"  # default addressing, tier-1
        assert item.reply_route["thread"] == THREAD_TS  # the way back

        # bot-self echoes and message subtypes are acked but never ingested
        await ws.send(_envelope("env-2", "Ev0002", {
            "type": "message", "subtype": "bot_message", "bot_id": "B1",
            "text": "my own echo", "channel": "C123",
        }))
        await ws.send(_envelope("env-3", "Ev0003", {
            "type": "message", "subtype": "message_changed",
            "message": {"user": "U-9", "text": "edited"}, "channel": "C123",
        }))
        assert await asyncio.wait_for(acks.get(), timeout=5) == "env-2"
        assert await asyncio.wait_for(acks.get(), timeout=5) == "env-3"
        await asyncio.sleep(0.3)
        assert len(await store.list_work_items(T)) == 1

        # --- link (b): one outbox row out -> chat.postMessage + acked --------
        await store.enqueue_channel_outbox(
            ChannelOutboxMessage(id="out-s1", tenant_id=T, channel_id="ch-s1",
                                 payload={"text": "hi back",
                                          "target": f"C123:{THREAD_TS}"})
        )
        (delivery,) = await _until(lambda: _delivered(posted))
        assert delivery["channel"] == "C123"
        assert delivery["thread_ts"] == THREAD_TS  # "channel:thread_ts" split
        assert delivery["text"] == "hi back"
        assert delivery["auth"] == "Bearer xoxb-test-token"  # bot token, never logged
        await _until(lambda: _settled(store))
        assert await store.claim_channel_outbox(T, ["ch-s1"], "late", 60, 10) == []
    finally:
        await daemon.stop()
        await asgi.aclose()
        await fake_api.aclose()
        socket_server.close()
        await socket_server.wait_closed()


async def _work_items(store):
    return await store.list_work_items(T)


async def _delivered(posted):
    return posted or None


async def _settled(store):
    msg = store._chan_outbox.get((T, "out-s1"))
    return msg is not None and msg.status == "delivered"
