"""HttpAdapter retry policy: only idempotent verbs auto-retry (NFR-REL).

A mutating call is never re-issued after a transport error or a 5xx: the
request may have landed before the connection dropped, and re-issuing it
would duplicate the side effect (e.g. a sent email).
"""

import socket

import httpx
import pytest

from boltrig.adapters.base import Credential, Result, VerbSpec
from boltrig.adapters.http_base import HttpAdapter, RetryPolicy
from boltrig.models import GrantSet, InvocationContext

T = "acme"
_PUBLIC_IP = "93.184.216.34"


class _Adapter(HttpAdapter):
    id = "t"
    version = "0.1.0"

    def describe(self) -> list[VerbSpec]:
        return [
            VerbSpec("t.read", "t", {"type": "object"}, {"type": "object"}, "low", "read"),
            VerbSpec("t.send", "t", {"type": "object"}, {"type": "object"}, "high", "send"),
        ]

    def _handlers(self):
        return {
            "t.read": self._read,
            "t.send": self._send,
        }

    async def _read(self, params, client, context):
        return Result.success(await self.request(client, "GET", "/read"))

    async def _send(self, params, client, context):
        return Result.success(await self.request(client, "POST", "/send"))


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port=None, *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (_PUBLIC_IP, port or 0))
        ],
    )


def _adapter(handler) -> _Adapter:
    adapter = _Adapter(base_url="https://api.example.test",
                       retry=RetryPolicy(max_attempts=3, base_delay=0))
    adapter._client = lambda credential: httpx.AsyncClient(  # test transport
        base_url=adapter.base_url, transport=httpx.MockTransport(handler)
    )
    return adapter


def _ctx():
    return InvocationContext(tenant_id=T, grants=GrantSet.of(["*"]), actor="tester")


def _cred():
    return Credential(id="T", kind="api_key", material={"value": "x"})


async def test_get_retries_a_5xx_up_to_max_attempts():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(503, json={})

    result = await _adapter(handler).execute("t.read", {}, _cred(), _ctx())

    assert not result.ok
    assert calls == ["/read", "/read", "/read"]


async def test_post_is_never_retried_after_a_5xx():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(503, json={})

    result = await _adapter(handler).execute("t.send", {}, _cred(), _ctx())

    assert not result.ok
    assert result.error is not None and result.error.error_class.value == "unavailable"
    assert calls == ["/send"]  # one attempt only: no duplicate side effect


async def test_post_is_never_retried_after_a_transport_error():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        raise httpx.ConnectError("dropped", request=request)

    result = await _adapter(handler).execute("t.send", {}, _cred(), _ctx())

    assert not result.ok
    assert calls == ["/send"]
