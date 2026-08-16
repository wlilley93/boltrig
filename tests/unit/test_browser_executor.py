from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import uvicorn
from fastapi.testclient import TestClient

from boltrig.adapters.base import Result, VerbSpec
from boltrig.adapters.builtin.browser_executor_client import execute_over_socket
from boltrig.fleet.browser_executor import create_app
from boltrig.models import GrantSet, InvocationContext


class _FakeBrowser:
    def __init__(self) -> None:
        self.calls = []

    def describe(self):
        return [VerbSpec("browser.snapshot", "browser", {"type": "object"}, {"type": "object"})]

    async def health(self):
        return "ok"

    async def execute(self, verb, params, credential, context):
        self.calls.append((verb, params, credential, context))
        return Result.success({"status": "ok", "owner": context.actor})


def test_browser_executor_refuses_non_protocol_and_unknown_verbs():
    browser = _FakeBrowser()
    client = TestClient(create_app(browser))
    payload = {
        "verb": "browser.snapshot",
        "params": {},
        "context": {"tenant_id": "acme", "owner_id": "user@example.com"},
    }

    assert client.post("/v1/execute", json=payload).status_code == 403
    refused = client.post(
        "/v1/execute",
        json={**payload, "verb": "browser.cdp.call"},
        headers={"x-boltrig-browser-protocol": "1"},
    )
    assert refused.status_code == 400
    assert browser.calls == []


def test_browser_executor_health_requires_its_live_chromium(
    monkeypatch,
):
    browser = _FakeBrowser()

    async def dead_cdp(_timeout: float) -> bool:
        return False

    monkeypatch.setattr("boltrig.fleet.stack_tool_health._probe_browser_cdp", dead_cdp)
    client = TestClient(create_app(browser, require_live_cdp=True))

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "down"}


async def test_private_unix_socket_carriage_preserves_owner_and_has_no_network_port():
    browser = _FakeBrowser()
    with tempfile.TemporaryDirectory(prefix="bex-", dir="/tmp") as root:
        socket_path = Path(root) / "browser.sock"
        config = uvicorn.Config(
            create_app(browser),
            uds=str(socket_path),
            lifespan="off",
            access_log=False,
            log_level="critical",
        )
        server = uvicorn.Server(config)
        task = asyncio.create_task(server.serve())
        await _wait_for_socket(socket_path)
        try:
            context = InvocationContext(
                tenant_id="acme",
                grants=GrantSet.of(["browser.snapshot"]),
                actor="agent",
                on_behalf_of="person@example.com",
            )
            result = await execute_over_socket(
                str(socket_path), "browser.snapshot", {"name": "workspace"}, context, timeout=2
            )
        finally:
            server.should_exit = True
            await task

    assert result.ok
    assert result.output == {"status": "ok", "owner": "person@example.com"}
    verb, params, credential, executed_context = browser.calls[0]
    assert (verb, params, credential) == ("browser.snapshot", {"name": "workspace"}, None)
    assert executed_context.tenant_id == "acme"
    assert executed_context.actor == "person@example.com"


async def _wait_for_socket(path: Path) -> None:
    for _ in range(100):
        if path.exists():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("browser executor Unix socket did not appear")
