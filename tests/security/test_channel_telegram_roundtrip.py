"""The Telegram Bot API long-poll adapter end-to-end proof (decision 0003;
SEC-177) - the mirror of test_channel_slack_roundtrip.py for the Telegram port
(ADDING_A_PLATFORM.md): the severed gateway, run in-process against a test
kernel over an ASGI transport, drives BOTH links through the Telegram adapter
against a FAKE Bot API (no network):

  fake Bot API (httpx MockTransport) - getMe authenticates; getUpdates
  long-poll returns queued updates and records the resume offset; sendMessage
  records what deliver() posted;

  inbound  - one forum-topic text message becomes a governed work item via the
             ONE signed intake route, its thread ("chat_id:message_thread_id")
             landing on the reply route as a complete deliver target; a bot
             message, a media-only message and a service update are polled past
             (the offset advances) but never ingested;
  outbound - one outbox row is claimed over the run-scoped token, delivered
             via sendMessage with the right body (chat_id:message_thread_id
             target split), and acked.
"""

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

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
SECRET = "telegramroundtrip_123"
CHAT_ID = "-100200300"
TOPIC_ID = 777

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
        Channel(id="ch-t1", tenant_id=T, platform="telegram", name="Telegram",
                transport="socket", credential_ref="cred-1",
                config={"sender_field": "sender"})
    )
    await store.set_credential_ref(T, "cred-1", {"secret": SECRET})
    await store.upsert_channel_binding(
        ChannelBinding(id="b-1", tenant_id=T, channel_id="ch-t1", platform="telegram",
                       external_user_id="424242", subject="alice", role="member")
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


def _update(update_id: int, message: dict | None) -> dict:
    update = {"update_id": update_id}
    if message is not None:
        update["message"] = message
    return update


@pytest.mark.security
@pytest.mark.invariant("SEC-177")
async def test_telegram_adapter_round_trip_against_a_test_kernel():
    kernel, store = await _kernel()
    kernel_app = create_app(kernel)
    asgi = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=kernel_app), base_url="http://test"
    )

    # --- the fake Bot API ----------------------------------------------------
    pending: asyncio.Queue = asyncio.Queue()   # updates getUpdates returns
    offsets: list[int] = []                    # resume cursors the adapter sent
    sent: list[dict] = []                      # sendMessage bodies

    async def _bot_api(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        if method == "getMe":
            return httpx.Response(200, json={"ok": True, "result": {
                "id": 9001, "is_bot": True, "username": "nabu_test_bot"}})
        if method == "getUpdates":
            # a tiny latency so the adapter's poll loop yields to the loop,
            # like a real long-poll call would
            await asyncio.sleep(0.01)
            body = json.loads(request.content)
            offsets.append(body.get("offset"))
            try:
                update = pending.get_nowait()
            except asyncio.QueueEmpty:
                update = None
            return httpx.Response(200, json={
                "ok": True, "result": [update] if update else []})
        if method == "sendMessage":
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 5}})
        return httpx.Response(404, json={"ok": False, "description": "unknown method"})

    fake_api = httpx.AsyncClient(transport=httpx.MockTransport(_bot_api))

    token = kernel.mcp.issue_run_token(
        T, GrantSet(), actor="channel-gateway",
        extra={"channel_gateway": True, "channels": ["ch-t1"]},
    )
    daemon = sidecar_app.ChannelSidecarDaemon(
        sidecar_app.KernelClient("http://test", token, client=asgi),
        [sidecar_app.ChannelSpec(
            channel_id="ch-t1", platform="telegram", secret=SECRET,
            config={
                "bot_token": "123456:test-token",
                "api_base": "http://127.0.0.1",
                "egress_allow": ["127.0.0.1"],
                "http_client": fake_api,
            },
        )],
        poll_seconds=0.05,
    )
    await daemon.start()
    try:
        # --- link (a): one forum-topic message in -> a governed work item ----
        await pending.put(_update(101, {
            "message_id": 9, "text": "hello nabu",
            "from": {"id": 424242, "is_bot": False, "first_name": "Alice"},
            "chat": {"id": int(CHAT_ID), "type": "supergroup"},
            "message_thread_id": TOPIC_ID,
        }))
        items = await _until(lambda: _work_items(store))
        (item,) = [w for w in items if w.on_behalf_of == "alice"]
        assert item.raw.get("text") == "hello nabu"
        assert item.raw.get("id") == "101"  # update_id is the delivery id
        assert item.target == "cos"  # default addressing, tier-1
        # the reply route carries a COMPLETE deliver target for the topic
        assert item.reply_route["thread"] == f"{CHAT_ID}:{TOPIC_ID}"

        # the resume cursor advanced past the ingested update
        await _until(lambda: _polled_past(offsets, 102))

        # bot messages, media-only messages and service updates are polled
        # past (offset advances) but never ingested
        await pending.put(_update(102, {
            "message_id": 10, "text": "my own echo",
            "from": {"id": 9001, "is_bot": True},
            "chat": {"id": int(CHAT_ID), "type": "supergroup"},
        }))
        await pending.put(_update(103, {
            "message_id": 11, "photo": [{"file_id": "x"}],
            "from": {"id": 424242, "is_bot": False},
            "chat": {"id": int(CHAT_ID), "type": "supergroup"},
        }))
        await pending.put(_update(104, None))  # a non-message update
        await _until(lambda: _polled_past(offsets, 105))
        await asyncio.sleep(0.3)
        assert len(await store.list_work_items(T)) == 1

        # --- link (b): one outbox row out -> sendMessage + acked -------------
        await store.enqueue_channel_outbox(
            ChannelOutboxMessage(id="out-t1", tenant_id=T, channel_id="ch-t1",
                                 payload={"text": "hi back",
                                          "target": f"{CHAT_ID}:{TOPIC_ID}"})
        )
        (delivery,) = await _until(lambda: _delivered(sent))
        assert delivery["chat_id"] == CHAT_ID
        assert delivery["message_thread_id"] == TOPIC_ID  # the "chat:topic" split
        assert delivery["text"] == "hi back"
        await _until(lambda: _settled(store))
        assert await store.claim_channel_outbox(T, ["ch-t1"], "late", 60, 10) == []
    finally:
        await daemon.stop()
        await asgi.aclose()
        await fake_api.aclose()


async def _work_items(store):
    return await store.list_work_items(T)


async def _polled_past(offsets, offset):
    seen = [o for o in offsets if o is not None]
    return seen and seen[-1] >= offset


async def _delivered(sent):
    return sent or None


async def _settled(store):
    msg = store._chan_outbox.get((T, "out-t1"))
    return msg is not None and msg.status == "delivered"
