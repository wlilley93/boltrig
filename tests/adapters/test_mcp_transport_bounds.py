"""The MCP transport reads a bounded body, like every other outbound adapter.

It did not. ``client.post`` followed by ``response.json()`` (or ``response.text``
for an SSE frame) let a registered MCP server choose how much memory this process
allocated, and compression made a megabyte on the wire worth gigabytes in RAM.
Discovery's page loop then multiplied that by the page ceiling.

Each test here asserts the refusal happens BEFORE the bytes are taken, which is
the only version of a bound that is worth having: counting after the fact is
counting an allocation that already happened.
"""

from __future__ import annotations

import httpx
import pytest

from boltrig.adapters.http_response import MAX_JSON_RESPONSE_BYTES
from boltrig.adapters.mcp_transport import StreamableHttp

_URL = "https://mcp.example.test/mcp"
_REQUEST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}


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


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.invariant("SEC-196")
async def test_a_declared_oversize_body_is_refused_without_reading_it():
    """Content-Length over the ceiling is refused before a single chunk moves."""
    stream = _CountingStream([b"{}"])

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(MAX_JSON_RESPONSE_BYTES + 1),
            },
            stream=stream,
        )

    async with _client(handler) as client:
        with pytest.raises(Exception) as caught:
            await StreamableHttp(_URL, client_version="test").call(client, _REQUEST, "token")

    assert "boundary" in str(caught.value).lower() or "limit" in str(caught.value).lower()
    assert stream.chunks_read == 0
    assert stream.closed is True


@pytest.mark.invariant("SEC-196")
async def test_a_chunked_body_stops_at_the_boundary():
    """A server that declares nothing and streams forever is stopped mid-read,
    rather than after it has already been allocated."""
    chunk = b"x" * (1024 * 1024)
    stream = _CountingStream([chunk for _ in range(8)])

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"Content-Type": "application/json"}, stream=stream
        )

    async with _client(handler) as client:
        with pytest.raises(Exception):
            await StreamableHttp(_URL, client_version="test").call(client, _REQUEST, "token")

    assert stream.chunks_read <= 5
    assert stream.closed is True


@pytest.mark.invariant("SEC-196")
async def test_identity_is_requested_and_a_compressed_body_is_refused():
    """The decompression bomb, in the one place that used to be open to it: a
    compressed body allocates its DECODED size inside httpx before any
    application-level check can see it."""
    stream = _CountingStream([b"compressed"])
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request.headers.get("accept-encoding", ""))
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
            stream=stream,
        )

    async with _client(handler) as client:
        with pytest.raises(Exception):
            await StreamableHttp(_URL, client_version="test").call(client, _REQUEST, "token")

    assert asked == ["identity"]
    assert stream.chunks_read == 0
    assert stream.closed is True


async def test_a_normal_response_still_round_trips():
    """The regression fence: bounding a body must not change the answer for
    every server that behaves."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "result": {"tools": []}},
        )

    async with _client(handler) as client:
        payload = await StreamableHttp(_URL, client_version="test").call(client, _REQUEST, "token")

    assert payload["result"] == {"tools": []}


async def test_an_sse_framed_response_still_decodes():
    """The SSE path reads response.text, so it is the other unbounded read - and
    it must keep working now that the body arrives buffered."""
    body = b'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n'

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"Content-Type": "text/event-stream"}, content=body
        )

    async with _client(handler) as client:
        payload = await StreamableHttp(_URL, client_version="test").call(client, _REQUEST, "token")

    assert payload["result"] == {"ok": True}
