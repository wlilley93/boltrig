"""The xAI Realtime voice adapter end-to-end proof (decision 0003; SEC-177,
SEC-183) - the mirror of test_channel_slack_roundtrip.py for the VOICE
platform port: the severed gateway, run in-process against a test kernel over
an ASGI transport, drives BOTH links through the voice adapter against a FAKE
xAI realtime server (an in-proc websockets server; no network):

  session bootstrap - the adapter discovers function tools over the run-scoped
      MCP token (tools/list), connects with a bearer header, and configures
      the session with the NESTED audio schema, server VAD and a tools list
      that is ONLY type:"function" entries generated from the granted verbs;
  inbound  - one completed transcript becomes a governed work item via the ONE
      signed intake route, its thread landing on the reply route;
  tools    - one function_call event is forwarded through POST /v1/mcp
      tools/call (the unchanged chokepoint - the ticket really is created and
      audited) and the result returns as a function_call_output item;
  barge-in - speech_started interrupts local playback and cancels the response;
  outbound - one outbox row is claimed over the run-scoped token, spoken via
      response.create, and acked.

Plus fail-closed init proofs: any config-injected xAI server-side tool
(web_search / x_search / remote mcp) is rejected at adapter init.
"""

import asyncio
import base64
import json
import sys
from pathlib import Path

import httpx
import pytest
import websockets

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
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
SECRET = "voiceroundtrip_123"

# The gateway is severed (no boltrig imports, SEC-28) - the TEST may straddle
# the boundary: it imports the gateway modules by path and the kernel normally.
_GATEWAY_DIR = str(Path(__file__).resolve().parents[2] / "services" / "channel_gateway")
if _GATEWAY_DIR not in sys.path:
    sys.path.insert(0, _GATEWAY_DIR)

import app as sidecar_app  # noqa: E402
import xai_voice_adapter  # noqa: E402


async def _kernel() -> tuple[Kernel, InMemoryStore, object]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    tickets = build_tickets()
    await kernel.register_adapter(T, tickets)
    await store.upsert_channel(
        Channel(id="ch-v1", tenant_id=T, platform="voice", name="Voice",
                transport="socket", credential_ref="cred-1",
                config={"sender_field": "sender"})
    )
    await store.set_credential_ref(T, "cred-1", {"secret": SECRET})
    await store.upsert_channel_binding(
        ChannelBinding(id="b-1", tenant_id=T, channel_id="ch-v1", platform="voice",
                       external_user_id="voice-user", subject="alice", role="member")
    )
    return kernel, store, tickets


async def _until(predicate, timeout: float = 5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        value = await predicate()
        if value:
            return value
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met within timeout")


async def _next_of_type(queue: asyncio.Queue, etype: str, timeout: float = 5.0) -> dict:
    """Pull client->server events until one of ``etype`` arrives."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        event = await asyncio.wait_for(queue.get(), timeout=max(0.05, deadline - asyncio.get_running_loop().time()))
        if event.get("type") == etype:
            return event
    raise AssertionError(f"no {etype} event within timeout")


@pytest.mark.security
@pytest.mark.invariant("SEC-177")
@pytest.mark.invariant("SEC-183")
async def test_voice_adapter_round_trip_against_a_test_kernel():
    kernel, store, tickets = await _kernel()
    kernel_app = create_app(kernel)
    asgi = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=kernel_app), base_url="http://test"
    )

    # --- the fake xAI realtime server ---------------------------------------
    sockets: asyncio.Queue = asyncio.Queue()   # accepted realtime conns
    received: asyncio.Queue = asyncio.Queue()  # client->server events
    seen_auth: list[str | None] = []

    async def _realtime_handler(ws):
        request = getattr(ws, "request", None)
        headers = getattr(request, "headers", {}) or {}
        seen_auth.append(headers.get("authorization"))
        await sockets.put(ws)
        try:
            async for raw in ws:
                try:
                    event = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                await received.put(event)
        except websockets.ConnectionClosed:
            pass

    realtime_server = await websockets.serve(_realtime_handler, "127.0.0.1", 0)
    realtime_port = realtime_server.sockets[0].getsockname()[1]

    audio = xai_voice_adapter.QueueAudio()
    token = kernel.mcp.issue_run_token(
        T, GrantSet.of(["ticket.create", "ticket.read"]), actor="channel-gateway",
        extra={"channel_gateway": True, "channels": ["ch-v1"]},
    )
    kernel_link = sidecar_app.KernelClient("http://test", token, client=asgi)
    daemon = sidecar_app.ChannelSidecarDaemon(
        kernel_link,
        [sidecar_app.ChannelSpec(
            channel_id="ch-v1", platform="voice", secret=SECRET,
            config={
                "api_key": "xai-test-key",
                "realtime_url": f"ws://127.0.0.1:{realtime_port}",
                "model": "test-realtime",
                "voice": "eve",
                "egress_allow": ["127.0.0.1"],
                "audio": audio,
                "kernel_client": kernel_link,
                "speaker": "voice-user",
                "thread": "voice:local",
            },
        )],
        poll_seconds=0.05,
    )
    await daemon.start()
    try:
        # --- session bootstrap: bearer auth + nested schema + function-only tools
        ws = await asyncio.wait_for(sockets.get(), timeout=5)
        update = await _next_of_type(received, "session.update")
        assert seen_auth == ["Bearer xai-test-key"]
        session = update["session"]
        assert session["audio"]["input"]["format"] == {"type": "audio/pcm", "rate": 24000}
        assert session["audio"]["input"]["turn_detection"] == {"type": "server_vad"}
        assert session["audio"]["output"]["voice"] == "eve"
        tools = session["tools"]
        assert tools and all(t["type"] == "function" for t in tools)
        names = {t["name"] for t in tools}
        assert names == {"ticket_create", "ticket_read"}  # mangled verb ids only

        # --- link (a): one transcript in -> a governed work item --------------
        await ws.send(json.dumps({
            "type": "conversation.item.input_audio_transcription.completed",
            "item_id": "item-0001", "transcript": "hello nabu",
        }))
        items = await _until(lambda: store.list_work_items(T))
        (item,) = [w for w in items if w.on_behalf_of == "alice"]
        assert item.raw.get("text") == "hello nabu"
        assert item.reply_route["thread"] == "voice:local"  # the way back

        # --- tools: one function_call out -> the chokepoint, result back in ---
        await ws.send(json.dumps({
            "type": "response.function_call_arguments.done",
            "call_id": "call-1", "name": "ticket_create",
            "arguments": json.dumps({"title": "from voice"}),
        }))
        output_item = await _next_of_type(received, "conversation.item.create")
        assert output_item["item"]["type"] == "function_call_output"
        assert output_item["item"]["call_id"] == "call-1"
        assert '"status": "open"' in output_item["item"]["output"]
        await _next_of_type(received, "response.create")
        # the call really ran the chokepoint: the ticket exists and was audited
        assert any(
            t.get("title") == "from voice" for t in tickets._tickets.values()
        )
        events = await store.audit_query(T)
        assert any(e.verb == "ticket.create" for e in events)

        # --- barge-in: speech interrupts playback and cancels the response ----
        await ws.send(json.dumps({
            "type": "response.output_audio.delta",
            "delta": base64.b64encode(b"pcm-chunk").decode("ascii"),
        }))
        await _until(lambda: _played(audio))
        assert audio.played == [b"pcm-chunk"]
        await ws.send(json.dumps({"type": "input_audio_buffer.speech_started"}))
        await _next_of_type(received, "response.cancel")
        assert audio.interrupted == 1
        assert audio.played == []  # interrupted playback drops the queue

        # --- mic seam: a local frame rides input_audio_buffer.append ----------
        audio.feed_mic(b"mic-frame")
        append = await _next_of_type(received, "input_audio_buffer.append")
        assert base64.b64decode(append["audio"]) == b"mic-frame"

        # --- link (b): one outbox row out -> spoken + acked --------------------
        await store.enqueue_channel_outbox(
            ChannelOutboxMessage(id="out-v1", tenant_id=T, channel_id="ch-v1",
                                 payload={"text": "hi back", "target": "voice:local"})
        )
        speak = await _next_of_type(received, "response.create")
        assert "hi back" in speak["response"]["instructions"]
        await _until(lambda: _settled(store))
        assert await store.claim_channel_outbox(T, ["ch-v1"], "late", 60, 10) == []
    finally:
        await daemon.stop()
        await asgi.aclose()
        realtime_server.close()
        await realtime_server.wait_closed()


async def _played(audio):
    return audio.played or None


async def _settled(store):
    msg = store._chan_outbox.get((T, "out-v1"))
    return msg is not None and msg.status == "delivered"


@pytest.mark.security
@pytest.mark.invariant("SEC-183")
@pytest.mark.parametrize(
    "key,tools",
    [
        ("tools", [{"type": "web_search"}]),
        ("tools", [{"type": "x_search"}]),
        ("server_tools", [{"type": "mcp", "server_url": "https://evil.example/mcp"}]),
        ("xai_tools", [{"type": "function", "name": "smuggled"}]),
    ],
)
def test_server_side_tool_config_is_rejected_at_init(key, tools):
    # session.tools is kernel-generated ONLY: an xAI server-side tool would
    # execute outside the chokepoint, and even a config function tool bypasses
    # discovery - both fail closed at init (before any socket opens).
    with pytest.raises(ValueError):
        xai_voice_adapter.XaiVoiceAdapter({
            "api_key": "xai-test-key",
            "egress_allow": ["api.x.ai"],
            key: tools,
        })


def test_missing_api_key_fails_closed():
    with pytest.raises(ValueError):
        xai_voice_adapter.XaiVoiceAdapter({"egress_allow": ["api.x.ai"]})
