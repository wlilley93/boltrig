"""The Discord gateway adapter end-to-end proof (decision 0003; SEC-177) - the
mirror of test_channel_slack_roundtrip.py for the Discord port
(ADDING_A_PLATFORM.md): the severed gateway, run in-process against a test
kernel over an ASGI transport, drives BOTH links through the Discord adapter
against a FAKE Discord (no network):

  fake REST (httpx MockTransport) - GET /gateway/bot returns the fake gateway
  URL; POST /channels/{id}/messages records what deliver() posted;
  fake WS gateway (websockets) - speaks the real lifecycle: HELLO with a
  heartbeat interval, expects IDENTIFY with intents, answers READY with
  session_id/resume_gateway_url, acks heartbeats, and dispatches events;

  inbound  - one MESSAGE_CREATE dispatch becomes a governed work item via the
             ONE signed intake route, its channel_id landing on the reply
             route; a bot-authored message and an empty-content message are
             sequenced but never ingested;
  lifecycle- the fake gateway observes IDENTIFY (with the message-content
             intent) and at least one well-formed heartbeat carrying the last
             dispatched seq;
  outbound - one outbox row is claimed over the run-scoped token, delivered
             via POST /channels/{target}/messages with the right body, and
             acked.
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
SECRET = "discordroundtrip_123"
CHANNEL_ID = "120034005000600700"
GUILD_CHANNEL = CHANNEL_ID

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
        Channel(id="ch-d1", tenant_id=T, platform="discord", name="Discord",
                transport="socket", credential_ref="cred-1",
                config={"sender_field": "sender"})
    )
    await store.set_credential_ref(T, "cred-1", {"secret": SECRET})
    await store.upsert_channel_binding(
        ChannelBinding(id="b-1", tenant_id=T, channel_id="ch-d1", platform="discord",
                       external_user_id="88112233", subject="alice", role="member")
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


def _dispatch(seq: int, dtype: str, data: dict) -> str:
    return json.dumps({"op": 0, "t": dtype, "s": seq, "d": data})


@pytest.mark.security
@pytest.mark.invariant("SEC-177")
async def test_discord_adapter_round_trip_against_a_test_kernel():
    kernel, store = await _kernel()
    kernel_app = create_app(kernel)
    asgi = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=kernel_app), base_url="http://test"
    )

    # --- the fake Discord gateway ---------------------------------------------
    sockets: asyncio.Queue = asyncio.Queue()   # accepted gateway conns
    identifies: list[dict] = []                # IDENTIFY payloads observed
    heartbeats: list[int | None] = []          # heartbeat seqs observed
    posted: list[dict] = []                    # create-message bodies + auth
    state: dict = {}                           # the bound port, once listening

    async def _gateway_handler(ws):
        await sockets.put(ws)
        # HELLO with a short heartbeat interval so the test observes beats
        await ws.send(json.dumps({"op": 10, "d": {"heartbeat_interval": 100}}))
        try:
            async for raw in ws:
                frame = json.loads(raw)
                if frame.get("op") == 2:  # IDENTIFY
                    identifies.append(frame["d"])
                    await ws.send(_dispatch(0, "READY", {
                        "session_id": "sess-fake-1",
                        "resume_gateway_url": f"ws://127.0.0.1:{state['port']}/",
                    }))
                elif frame.get("op") == 1:  # HEARTBEAT -> ack it
                    heartbeats.append(frame.get("d"))
                    await ws.send(json.dumps({"op": 11}))
        except websockets.ConnectionClosed:
            pass

    gateway_server = await websockets.serve(_gateway_handler, "127.0.0.1", 0)
    gateway_port = gateway_server.sockets[0].getsockname()[1]
    state["port"] = gateway_port

    def _discord_api(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/gateway/bot"):
            return httpx.Response(200, json={"url": f"ws://127.0.0.1:{gateway_port}"})
        if "/channels/" in request.url.path and request.url.path.endswith("/messages"):
            posted.append({
                "auth": request.headers.get("authorization"),
                "path": request.url.path,
                **json.loads(request.content),
            })
            return httpx.Response(200, json={"id": "999000111"})
        return httpx.Response(404, json={"message": "unknown"})

    fake_api = httpx.AsyncClient(transport=httpx.MockTransport(_discord_api))

    token = kernel.mcp.issue_run_token(
        T, GrantSet(), actor="channel-gateway",
        extra={"channel_gateway": True, "channels": ["ch-d1"]},
    )
    daemon = sidecar_app.ChannelSidecarDaemon(
        sidecar_app.KernelClient("http://test", token, client=asgi),
        [sidecar_app.ChannelSpec(
            channel_id="ch-d1", platform="discord", secret=SECRET,
            config={
                "bot_token": "discord-test-token",
                "api_base": "http://127.0.0.1/api/v10",
                "egress_allow": ["127.0.0.1"],
                "http_client": fake_api,
            },
        )],
        poll_seconds=0.05,
    )
    await daemon.start()
    try:
        # the adapter comes up, IDENTIFYs with intents, and heartbeats
        ws = await asyncio.wait_for(sockets.get(), timeout=5)
        (identify,) = await _until(lambda: _seen(identifies))
        assert identify["intents"] & (1 << 15)  # MESSAGE_CONTENT requested
        await _until(lambda: _seen(heartbeats))

        # --- link (a): one MESSAGE_CREATE in -> a governed work item ---------
        await ws.send(_dispatch(1, "MESSAGE_CREATE", {
            "id": "5550001", "channel_id": CHANNEL_ID, "content": "hello nabu",
            "author": {"id": "88112233", "username": "alice"},
        }))
        items = await _until(lambda: _work_items(store))
        (item,) = [w for w in items if w.on_behalf_of == "alice"]
        assert item.raw.get("text") == "hello nabu"
        assert item.raw.get("id") == "5550001"  # the message id dedups replays
        assert item.target == "cos"  # default addressing, tier-1
        assert item.reply_route["thread"] == CHANNEL_ID  # the way back

        # bot-authored and empty-content messages are sequenced but ignored
        await ws.send(_dispatch(2, "MESSAGE_CREATE", {
            "id": "5550002", "channel_id": CHANNEL_ID, "content": "my own echo",
            "author": {"id": "9001", "bot": True},
        }))
        await ws.send(_dispatch(3, "MESSAGE_CREATE", {
            "id": "5550003", "channel_id": CHANNEL_ID, "content": "",
            "author": {"id": "88112233"}, "attachments": [{"id": "a1"}],
        }))
        await _until(lambda: _beat_past(heartbeats, 3))
        await asyncio.sleep(0.3)
        assert len(await store.list_work_items(T)) == 1

        # --- link (b): one outbox row out -> create message + acked -----------
        await store.enqueue_channel_outbox(
            ChannelOutboxMessage(id="out-d1", tenant_id=T, channel_id="ch-d1",
                                 payload={"text": "hi back", "target": CHANNEL_ID})
        )
        (delivery,) = await _until(lambda: _delivered(posted))
        assert delivery["path"] == f"/api/v10/channels/{CHANNEL_ID}/messages"
        assert delivery["content"] == "hi back"
        assert delivery["auth"] == "Bot discord-test-token"  # bot token, never logged
        await _until(lambda: _settled(store))
        assert await store.claim_channel_outbox(T, ["ch-d1"], "late", 60, 10) == []
    finally:
        await daemon.stop()
        await asgi.aclose()
        await fake_api.aclose()
        gateway_server.close()
        await gateway_server.wait_closed()


async def _work_items(store):
    return await store.list_work_items(T)


async def _seen(frames):
    return frames or None


async def _beat_past(heartbeats, seq):
    # heartbeats carry the last seq the adapter saw; wait for one at/past seq
    return [h for h in heartbeats if h is not None and h >= seq] or None


async def _delivered(posted):
    return posted or None


async def _settled(store):
    msg = store._chan_outbox.get((T, "out-d1"))
    return msg is not None and msg.status == "delivered"
