from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable

import pytest

from boltrig.fleet.infrastructure import codex_protocol as wire
from boltrig.fleet.infrastructure.codex_app_server import CodexAppServerClient

INITIALIZE_RESULT: dict[str, object] = {
    "codexHome": "/srv/boltrig/codex-home",
    "platformFamily": "unix",
    "platformOs": "linux",
    "userAgent": "boltrig/0.1.0 codex/0.144.3",
}


def thread_payload(
    thread_id: str = "thr-1", *, cwd: str = "/workspace", ephemeral: bool = True
) -> dict[str, object]:
    return {
        "cliVersion": "0.144.3",
        "createdAt": 1,
        "cwd": cwd,
        "ephemeral": ephemeral,
        "id": thread_id,
        "modelProvider": "openai",
        "preview": "",
        "sessionId": "session-1",
        "source": "appServer",
        "status": {"type": "idle"},
        "turns": [],
        "updatedAt": 1,
    }


def thread_result(
    thread_id: str = "thr-1",
    *,
    cwd: str = "/workspace",
    model: str = "gpt-5.4",
) -> dict[str, object]:
    return {
        "approvalPolicy": "never",
        "approvalsReviewer": "user",
        "cwd": cwd,
        "model": model,
        "modelProvider": "openai",
        "sandbox": {"type": "readOnly", "networkAccess": False},
        "thread": thread_payload(thread_id, cwd=cwd),
    }


class FakeLineTransport:
    def __init__(self) -> None:
        self.sent: asyncio.Queue[str] = asyncio.Queue()
        self.incoming: asyncio.Queue[str | Exception] = asyncio.Queue()
        self.write_error: Exception | None = None
        self.write_gate: asyncio.Event | None = None
        self.write_started = asyncio.Event()
        self.read_limits: list[int] = []
        self.close_failures = 0
        self.close_calls = 0
        self.closed = False

    async def write_line(self, line: str) -> None:
        self.write_started.set()
        if self.write_gate is not None:
            await self.write_gate.wait()
        if self.write_error is not None:
            raise self.write_error
        await self.sent.put(line)

    async def read_line(self, max_bytes: int) -> str:
        self.read_limits.append(max_bytes)
        value = await self.incoming.get()
        if isinstance(value, Exception):
            raise value
        if len(value.encode("utf-8")) > max_bytes:
            raise ValueError("frame exceeds allocation bound")
        return value

    async def aclose(self) -> None:
        self.close_calls += 1
        if self.close_failures:
            self.close_failures -= 1
            raise RuntimeError("SECRET close detail")
        self.closed = True

    async def receive(self, value: dict[str, object] | str | Exception) -> None:
        if isinstance(value, dict):
            await self.incoming.put(json.dumps(value, separators=(",", ":")))
        else:
            await self.incoming.put(value)


ClientFactory = Callable[..., tuple[CodexAppServerClient, FakeLineTransport]]


@pytest.fixture
async def client_factory() -> AsyncIterator[ClientFactory]:
    clients: list[CodexAppServerClient] = []

    def make(
        *,
        request_timeout: float = 0.2,
        max_pending: int = 4,
        max_notifications: int = 8,
        max_notification_bytes: int = 4096,
        response_history: int = 8,
        max_tombstones: int = 8,
        server_request_handler: object = None,
    ) -> tuple[CodexAppServerClient, FakeLineTransport]:
        transport = FakeLineTransport()
        client = CodexAppServerClient(
            transport,
            request_timeout=request_timeout,
            max_pending=max_pending,
            max_notifications=max_notifications,
            max_notification_bytes=max_notification_bytes,
            response_history=response_history,
            max_tombstones=max_tombstones,
            server_request_handler=server_request_handler,
        )
        clients.append(client)
        return client, transport

    yield make
    await asyncio.gather(*(client.aclose() for client in clients), return_exceptions=True)


async def sent(transport: FakeLineTransport) -> wire.WireMessage:
    line = await asyncio.wait_for(transport.sent.get(), timeout=0.2)
    return wire.decode_message(line)


async def initialize(
    client: CodexAppServerClient, transport: FakeLineTransport
) -> wire.CallReceipt:
    task = asyncio.create_task(client.initialize())
    request = await sent(transport)
    assert isinstance(request, wire.RequestMessage)
    assert (request.request_id, request.method) == (1, "initialize")
    await transport.receive({"id": 1, "result": INITIALIZE_RESULT})
    receipt = await task
    assert await sent(transport) == wire.NotificationMessage("initialized")
    return receipt
