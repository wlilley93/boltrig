"""The Signal (signal-cli JSON-RPC/SSE) adapter end-to-end proof (decision
0003; SEC-177) - the mirror of test_channel_slack_roundtrip.py for the Signal
port (ADDING_A_PLATFORM.md): the severed gateway, run in-process against a
test kernel over an ASGI transport, drives BOTH links through the Signal
adapter against a FAKE signal-cli daemon (no real Signal network):

  fake signal-cli (a raw asyncio TCP server speaking minimal HTTP/1.1) -
  GET /api/v1/check answers liveness; GET /api/v1/events streams SSE
  envelopes; POST /api/v1/rpc records JSON-RPC calls and answers results;

  inbound  - one DM envelope becomes a governed work item via the ONE signed
             intake route, its source number landing on the reply route as the
             deliver target; receipt/typing envelopes, a contentless envelope
             and a self-echo are streamed past but never ingested;
  outbound - two outbox rows are claimed over the run-scoped token and
             delivered via the JSON-RPC ``send`` method - a DM (recipient) and
             a group (groupId) - then acked.
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
SECRET = "signalroundtrip_123"
ACCOUNT = "+1555000111"
ALICE = "+1555222333"
GROUP_ID = "Z3JvdXAtYmFzZTY0"

# The gateway is severed (no boltrig imports, SEC-28) - the TEST may straddle
# the boundary: it imports the gateway modules by path and the kernel normally.
_GATEWAY_DIR = str(Path(__file__).resolve().parents[2] / "services" / "channel_gateway")
if _GATEWAY_DIR not in sys.path:
    sys.path.insert(0, _GATEWAY_DIR)

import app as sidecar_app  # noqa: E402


class _FakeSignalCli:
    """A fake signal-cli daemon: minimal HTTP/1.1 over a raw socket, SSE for
    inbound envelopes, JSON-RPC over POST for outbound sends."""

    def __init__(self) -> None:
        self.rpc_calls: list[dict] = []
        self.sse_writers: list[asyncio.StreamWriter] = []
        self.server: asyncio.AbstractServer | None = None
        self.port = 0

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        for writer in self.sse_writers:
            writer.close()
        self.sse_writers.clear()
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()

    async def push(self, envelope: dict) -> None:
        line = f"data: {json.dumps(envelope)}\n\n".encode()
        for writer in self.sse_writers:
            writer.write(line)
            await writer.drain()

    async def _handle(self, reader, writer) -> None:
        request_line = await reader.readline()
        headers: dict[str, str] = {}
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
            key, _, value = line.decode().partition(":")
            headers[key.strip().lower()] = value.strip()
        path = request_line.decode().split(" ")[1] if request_line else ""
        if path.startswith("/api/v1/events"):
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n\r\n")
            await writer.drain()
            self.sse_writers.append(writer)
            return  # the stream stays open until teardown
        length = int(headers.get("content-length") or 0)
        body = await reader.readexactly(length) if length else b""
        if path.startswith("/api/v1/check"):
            await self._respond(writer, b'{"status":"ok"}')
        elif path.startswith("/api/v1/rpc"):
            request = json.loads(body)
            self.rpc_calls.append(request)
            payload = json.dumps({
                "jsonrpc": "2.0",
                "result": {"timestamp": 1720000000001},
                "id": request.get("id"),
            }).encode()
            await self._respond(writer, payload)
        else:
            writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
        writer.close()

    @staticmethod
    async def _respond(writer, payload: bytes) -> None:
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
            + str(len(payload)).encode() + b"\r\n\r\n" + payload
        )
        await writer.drain()


async def _kernel() -> tuple[Kernel, InMemoryStore]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    await store.upsert_channel(
        Channel(id="ch-sig1", tenant_id=T, platform="signal", name="Signal",
                transport="socket", credential_ref="cred-1",
                config={"sender_field": "sender"})
    )
    await store.set_credential_ref(T, "cred-1", {"secret": SECRET})
    await store.upsert_channel_binding(
        ChannelBinding(id="b-1", tenant_id=T, channel_id="ch-sig1", platform="signal",
                       external_user_id=ALICE, subject="alice", role="member")
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
async def test_signal_adapter_round_trip_against_a_test_kernel():
    kernel, store = await _kernel()
    kernel_app = create_app(kernel)
    asgi = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=kernel_app), base_url="http://test"
    )
    fake = _FakeSignalCli()
    await fake.start()

    token = kernel.mcp.issue_run_token(
        T, GrantSet(), actor="channel-gateway",
        extra={"channel_gateway": True, "channels": ["ch-sig1"]},
    )
    daemon = sidecar_app.ChannelSidecarDaemon(
        sidecar_app.KernelClient("http://test", token, client=asgi),
        [sidecar_app.ChannelSpec(
            channel_id="ch-sig1", platform="signal", secret=SECRET,
            config={
                "http_url": f"http://127.0.0.1:{fake.port}",
                "account": ACCOUNT,
                "egress_allow": ["127.0.0.1"],
            },
        )],
        poll_seconds=0.05,
    )
    await daemon.start()
    try:
        # the adapter checks the daemon and opens the SSE stream
        await _until(lambda: _seen(fake.sse_writers))

        # --- link (a): one DM envelope in -> a governed work item -------------
        await fake.push({"envelope": {
            "sourceNumber": ALICE, "sourceName": "Alice",
            "timestamp": 1720000000000,
            "dataMessage": {"message": "hello nabu", "timestamp": 1720000000000},
        }})
        items = await _until(lambda: _work_items(store))
        (item,) = [w for w in items if w.on_behalf_of == "alice"]
        assert item.raw.get("text") == "hello nabu"
        assert item.raw.get("id") == "1720000000000"  # the envelope timestamp
        assert item.target == "cos"  # default addressing, tier-1
        assert item.reply_route["thread"] == ALICE  # a complete deliver target

        # receipts, typing, contentless envelopes and self-echoes are ignored
        await fake.push({"envelope": {"sourceNumber": ALICE, "timestamp": 1720000000002,
                                      "receiptMessage": {"when": 1}}})
        await fake.push({"envelope": {"sourceNumber": ALICE, "timestamp": 1720000000003,
                                      "typingMessage": {"action": "STARTED"}}})
        await fake.push({"envelope": {"sourceNumber": ALICE, "timestamp": 1720000000004,
                                      "dataMessage": {"message": ""}}})
        await fake.push({"envelope": {"sourceNumber": ACCOUNT, "timestamp": 1720000000005,
                                      "dataMessage": {"message": "my own echo"}}})
        await asyncio.sleep(0.3)
        assert len(await store.list_work_items(T)) == 1

        # --- link (b): DM + group outbox rows out -> JSON-RPC send + acked -----
        await store.enqueue_channel_outbox(
            ChannelOutboxMessage(id="out-sig1", tenant_id=T, channel_id="ch-sig1",
                                 payload={"text": "hi back", "target": ALICE})
        )
        await store.enqueue_channel_outbox(
            ChannelOutboxMessage(id="out-sig2", tenant_id=T, channel_id="ch-sig1",
                                 payload={"text": "group hi",
                                          "target": f"group:{GROUP_ID}"})
        )
        calls = await _until(lambda: _rpc_sends(fake.rpc_calls))
        by_text = {c["params"]["message"]: c["params"] for c in calls}
        assert by_text["hi back"]["account"] == ACCOUNT
        assert by_text["hi back"]["recipient"] == [ALICE]  # a DM target
        assert by_text["group hi"]["groupId"] == GROUP_ID  # "group:<id>" split
        assert all(c["method"] == "send" and c["jsonrpc"] == "2.0" for c in calls)
        await _until(lambda: _settled(store))
        assert await store.claim_channel_outbox(T, ["ch-sig1"], "late", 60, 10) == []
    finally:
        await daemon.stop()
        await asgi.aclose()
        await fake.stop()


async def _work_items(store):
    return await store.list_work_items(T)


async def _seen(writers):
    return writers or None


async def _rpc_sends(calls):
    sends = [c for c in calls if c.get("method") == "send"]
    return sends if len(sends) >= 2 else None


async def _settled(store):
    done = [
        msg.status == "delivered"
        for key in ((T, "out-sig1"), (T, "out-sig2"))
        if (msg := store._chan_outbox.get(key)) is not None
    ]
    return done if len(done) == 2 and all(done) else None
