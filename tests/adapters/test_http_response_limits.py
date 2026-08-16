"""Outbound adapter responses are bounded before they enter application memory."""

from __future__ import annotations

import base64
import httpx
import pytest

import boltrig.adapters.builtin.web_fetch as web_fetch
import boltrig.adapters.egress as egress
from boltrig.adapters.base import Credential, Result, VerbSpec
from boltrig.adapters.builtin.local_whisper import LocalWhisperAdapter
from boltrig.adapters.http_base import HttpAdapter, RetryPolicy
from boltrig.adapters.http_response import MAX_JSON_RESPONSE_BYTES
from boltrig.models import GrantSet, InvocationContext

T = "acme"
_PUBLIC_IP = "93.184.216.34"


class _CountingStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.chunks_read = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self._chunks:
            self.chunks_read += 1
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


class _BoundaryAdapter(HttpAdapter):
    id = "boundary-test"
    version = "1.0.0"

    def describe(self) -> list[VerbSpec]:
        return [
            VerbSpec(
                "boundary.read",
                "boundary",
                {"type": "object"},
                {"type": "object"},
                "low",
                "read",
            )
        ]

    def _handlers(self):
        return {"boundary.read": self._read}

    async def _read(self, params, client, context):
        return Result.success(await self.request(client, "GET", "/read"))


def _ctx() -> InvocationContext:
    return InvocationContext(
        tenant_id=T,
        grants=GrantSet.of(["*"]),
        actor="boundary-test",
    )


def _credential() -> Credential:
    return Credential(id="TEST", kind="api_key", material={"value": "x"})


def _http_adapter(handler) -> _BoundaryAdapter:
    adapter = _BoundaryAdapter(
        base_url=f"https://{_PUBLIC_IP}",
        retry=RetryPolicy(max_attempts=3, base_delay=0),
    )
    adapter._client = lambda _credential: httpx.AsyncClient(  # type: ignore[method-assign]
        base_url=adapter.base_url,
        transport=httpx.MockTransport(handler),
    )
    return adapter


@pytest.mark.invariant("SEC-196")
async def test_web_fetch_returns_a_bounded_prefix_without_draining_upstream(
    monkeypatch,
):
    stream = _CountingStream([b"x" * (256 * 1024) for _ in range(8)])
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(
            200,
            headers={"Content-Type": "text/plain"},
            stream=stream,
        )

    monkeypatch.setattr(web_fetch, "_resolve", lambda _host: [_PUBLIC_IP])
    monkeypatch.setattr(
        egress,
        "pinned_async_client_for_ip",
        lambda *_args, **_kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ),
    )

    result = await web_fetch.build_web_fetch_adapter({}).execute(
        "web.fetch",
        {"url": "https://example.com/large", "max_bytes": 1024},
        None,
        _ctx(),
    )

    assert result.ok
    assert result.output["content"] == "x" * 1024
    assert result.output["truncated"] is True
    assert stream.chunks_read == 1
    assert stream.closed is True
    assert seen_headers["accept-encoding"] == "identity"


@pytest.mark.parametrize("invalid", [0, -1, True, "1024", None])
async def test_web_fetch_rejects_invalid_response_bounds_before_network(
    monkeypatch, invalid
):
    monkeypatch.setattr(web_fetch, "_resolve", lambda _host: [_PUBLIC_IP])
    monkeypatch.setattr(
        egress,
        "pinned_async_client_for_ip",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("invalid bounds must not open a network client")
        ),
    )

    result = await web_fetch.build_web_fetch_adapter({}).execute(
        "web.fetch",
        {"url": "https://example.com", "max_bytes": invalid},
        None,
        _ctx(),
    )

    assert not result.ok
    assert result.error is not None
    assert result.error.error_class.value == "invalid"


@pytest.mark.invariant("SEC-196")
async def test_json_adapter_rejects_declared_oversize_without_read_or_retry():
    stream = _CountingStream([b"{}"])
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(MAX_JSON_RESPONSE_BYTES + 1),
            },
            stream=stream,
        )

    result = await _http_adapter(handler).execute(
        "boundary.read", {}, _credential(), _ctx()
    )

    assert not result.ok
    assert result.error is not None
    assert result.error.error_class.value == "unavailable"
    assert result.error.retryable is False
    assert calls == 1
    assert stream.chunks_read == 0
    assert stream.closed is True


@pytest.mark.invariant("SEC-196")
async def test_json_adapter_stops_a_chunked_response_at_the_boundary():
    chunk = b"x" * (1024 * 1024)
    stream = _CountingStream([chunk for _ in range(8)])

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            stream=stream,
        )

    result = await _http_adapter(handler).execute(
        "boundary.read", {}, _credential(), _ctx()
    )

    assert not result.ok
    assert result.error is not None
    assert result.error.error_class.value == "unavailable"
    assert stream.chunks_read == 5
    assert stream.closed is True


@pytest.mark.invariant("SEC-196")
async def test_json_adapter_rejects_compression_before_body_iteration():
    stream = _CountingStream([b"compressed"])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(
            200,
            headers={"Content-Encoding": "gzip"},
            stream=stream,
        )

    result = await _http_adapter(handler).execute(
        "boundary.read", {}, _credential(), _ctx()
    )

    assert not result.ok
    assert result.error is not None
    assert result.error.error_class.value == "unavailable"
    assert stream.chunks_read == 0
    assert stream.closed is True


@pytest.mark.invariant("SEC-196")
async def test_local_voice_transcription_uses_the_same_json_response_boundary():
    stream = _CountingStream([b'\x7b"text":"must-not-be-read"\x7d'])

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Length": str(MAX_JSON_RESPONSE_BYTES + 1)},
            stream=stream,
        )

    adapter = LocalWhisperAdapter(
        base_url="http://127.0.0.1:8910",
        transport=httpx.MockTransport(handler),
    )
    result = await adapter.execute(
        "voice.listen",
        {"audio_b64": base64.b64encode(b"audio").decode("ascii")},
        None,
        _ctx(),
    )

    assert not result.ok
    assert result.error is not None
    assert result.error.error_class.value == "unavailable"
    assert result.error.retryable is False
    assert stream.chunks_read == 0
    assert stream.closed is True
