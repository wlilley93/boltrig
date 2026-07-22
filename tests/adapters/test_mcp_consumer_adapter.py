"""MCP consumer adapter: transport failures are typed, standard content maps.

The HTTP-path suites pin the transport interop (see the adapter module's
"Transport interop" section): a plain JSON-RPC door (the Boltrig-face / Opbox
convention) is used session-less with no handshake, while a strict
Streamable-HTTP door gets the lazy initialize handshake, the session id it
issued, and SSE-framed answers decoded back to JSON-RPC payloads. Both doors
are stubbed at the pinned-HTTP seam (``pinned_async_client``), so what the
consumer would put on the wire is directly observable.
"""

import json

import pytest

from boltrig.adapters.base import Credential
from boltrig.adapters.mcp_consumer import McpConsumerAdapter
from boltrig.models import GrantSet, InvocationContext

T = "acme"


def _ctx():
    return InvocationContext(tenant_id=T, grants=GrantSet.of(["*"]), actor="tester")


def _cred():
    return Credential(id="MCP", kind="api_key", material={"value": "secret"})


def _adapter(rpc) -> McpConsumerAdapter:
    adapter = McpConsumerAdapter(id="mcp-x", rpc=rpc)
    adapter.review_and_activate("reviewer@acme")
    return adapter


async def test_standard_mcp_content_falls_back_to_text_output():
    async def rpc(request):
        # A non-Boltrig MCP server: no _boltrig envelope, standard content array.
        return {"jsonrpc": "2.0", "id": 2, "result": {
            "content": [{"type": "text", "text": "hello"},
                        {"type": "image", "data": "..."},
                        {"type": "text", "text": "world"}],
        }}

    result = await _adapter(rpc).execute("tool.x", {}, _cred(), _ctx())

    assert result.ok
    assert result.output == {"text": "hello\nworld"}


async def test_boltrig_envelope_still_wins_over_content():
    async def rpc(request):
        return {"jsonrpc": "2.0", "id": 2, "result": {
            "_boltrig": {"output": {"structured": True}},
            "content": [{"type": "text", "text": "ignored"}],
        }}

    result = await _adapter(rpc).execute("tool.x", {}, _cred(), _ctx())

    assert result.ok
    assert result.output == {"structured": True}


async def test_transport_failure_is_typed_not_raised():
    async def rpc(request):
        raise ConnectionError("boom")

    result = await _adapter(rpc).execute("tool.x", {}, _cred(), _ctx())

    # US-ADP-06: a failing MCP server must not crash the kernel; the raw
    # exception becomes a typed INTERNAL failure.
    assert not result.ok
    assert result.error is not None
    assert result.error.error_class.value == "internal"


# --- HTTP-path doors (stubbed at the pinned_client seam) ---


class _HttpResp:
    """The httpx response shape the consumer reads: status, headers, payload."""

    def __init__(self, payload=None, *, status=200, headers=None, text=""):
        self._payload = payload
        self.status_code = status
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._payload


def _sse(payload: dict, *, headers=None) -> _HttpResp:
    """An SSE-framed JSON-RPC answer, the strict Streamable-HTTP shape."""
    return _HttpResp(
        headers={"content-type": "text/event-stream", **(headers or {})},
        text=f"event: message\ndata: {json.dumps(payload)}\n\n",
    )


def _http_consumer(monkeypatch, door) -> McpConsumerAdapter:
    monkeypatch.setattr(
        "boltrig.adapters.egress.pinned_async_client", lambda url, timeout: door
    )
    return McpConsumerAdapter("ext-mcp", url="https://mcp.example.com/mcp")


_TOOLS = [{"name": "ticket.read", "description": "read a ticket", "inputSchema": {}}]


class _PlainDoor:
    """A plain JSON-RPC MCP door - the Boltrig face's and the Opbox kernel's
    shape: no handshake, no session, plain JSON 200 answers."""

    def __init__(self, tools):
        self.tools = tools
        self.posts: list[tuple[str, dict]] = []  # (method, headers) on the wire

    async def post(self, url, json, headers):  # noqa: ANN001 - httpx-shaped stub
        self.posts.append((json.get("method"), dict(headers)))
        if json.get("method") == "tools/list":
            return _HttpResp({"jsonrpc": "2.0", "id": json["id"],
                              "result": {"tools": self.tools}})
        return _HttpResp({"jsonrpc": "2.0", "id": json.get("id"), "result": {
            "content": [{"type": "text", "text": "done"}]}})

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.mark.invariant("FR-MCP-03")
async def test_a_plain_jsonrpc_door_gets_no_handshake_and_both_credential_headers(monkeypatch):
    """The Boltrig/Opbox convention: calls answer directly, so the lazy
    handshake never fires - and every POST carries BOTH credential conventions
    (Authorization bearer AND x-boltrig-mcp-token) plus the SSE-tolerant Accept."""
    door = _PlainDoor(list(_TOOLS))
    consumer = _http_consumer(monkeypatch, door)
    cred = Credential(id="MCP", kind="api_key", material={"value": "tok-1"})

    specs = await consumer.connect(cred)
    consumer.review_and_activate("reviewer@acme")
    result = await consumer.execute("ticket.read", {}, cred, _ctx())

    assert [s.verb_id for s in specs] == ["ticket.read"]
    assert result.ok and result.output == {"text": "done"}
    assert [m for m, _ in door.posts] == ["tools/list", "tools/call"]  # no initialize
    for _, headers in door.posts:
        assert headers["Authorization"] == "Bearer tok-1"  # the spec convention
        assert headers["x-boltrig-mcp-token"] == "tok-1"  # the Boltrig convention
        assert "text/event-stream" in headers["Accept"]
        assert "Mcp-Session-Id" not in headers


class _StrictDoor:
    """A spec-strict Streamable-HTTP MCP server: requires the bearer, the
    SSE-tolerant Accept header, and a live session - refusing any non-initialize
    method without one (400) - and frames every JSON-RPC answer as SSE.
    Initialize mints the session id the client must then carry."""

    def __init__(self, tools):
        self.tools = tools
        self.posts: list[tuple[str, dict]] = []
        self.live_sessions: set[str] = set()
        self._mints = 0

    async def post(self, url, json, headers):  # noqa: ANN001 - httpx-shaped stub
        method = json.get("method")
        # HTTP header names are case-insensitive on the wire; normalise like a
        # real server stack would before enforcing.
        headers = {str(k).lower(): v for k, v in headers.items()}
        if not str(headers.get("authorization", "")).startswith("Bearer "):
            return _HttpResp(status=401)
        if "text/event-stream" not in str(headers.get("accept", "")):
            return _HttpResp(status=406)
        self.posts.append((method, dict(headers)))
        if method == "initialize":
            self._mints += 1
            session = f"sess-{self._mints}"
            self.live_sessions.add(session)
            return _sse(
                {"jsonrpc": "2.0", "id": json["id"], "result": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "strict-fake", "version": "0"},
                }},
                headers={"mcp-session-id": session},
            )
        if headers.get("mcp-session-id") not in self.live_sessions:
            return _HttpResp(status=400)  # no live session: the spec's refusal
        if method == "notifications/initialized":
            return _HttpResp(status=202)
        if method == "tools/list":
            return _sse({"jsonrpc": "2.0", "id": json["id"],
                         "result": {"tools": self.tools}})
        if method == "tools/call":
            return _sse({"jsonrpc": "2.0", "id": json["id"], "result": {
                "content": [{"type": "text", "text": "strict-ok"}]}})
        return _HttpResp(status=400)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.mark.invariant("FR-MCP-03")
async def test_a_strict_streamable_http_door_gets_the_full_round_trip(monkeypatch):
    """connect -> tools/list -> tools/call against a door that REQUIRES the
    initialize handshake, the session id it issues, the bearer header, and
    SSE-framed answers: the first plain call is refused (400), the lazy
    handshake runs, and the retried call carries the issued session."""
    door = _StrictDoor(list(_TOOLS))
    consumer = _http_consumer(monkeypatch, door)
    cred = Credential(id="MCP", kind="api_key", material={"value": "tok-strict"})

    specs = await consumer.connect(cred)
    consumer.review_and_activate("reviewer@acme")
    result = await consumer.execute("ticket.read", {}, cred, _ctx())

    assert [s.verb_id for s in specs] == ["ticket.read"]
    assert result.ok and result.output == {"text": "strict-ok"}  # SSE-decoded
    assert [m for m, _ in door.posts] == [
        "tools/list",  # refused (400): no session yet
        "initialize", "notifications/initialized",  # the lazy handshake
        "tools/list",  # retried, now with the session
        "tools/call",
    ]
    seen_initialize = False
    for method, headers in door.posts:
        if method == "initialize":
            seen_initialize = True
        elif seen_initialize:
            assert headers.get("mcp-session-id") == "sess-1"


@pytest.mark.invariant("FR-MCP-03")
async def test_an_expired_session_re_handshakes_once_and_retries(monkeypatch):
    """A strict door that forgets the session (restart/expiry) refuses the next
    call; the consumer re-initializes once and the retried call succeeds on the
    fresh session - bounded, not a loop."""
    door = _StrictDoor(list(_TOOLS))
    consumer = _http_consumer(monkeypatch, door)
    cred = Credential(id="MCP", kind="api_key", material={"value": "tok-strict"})
    await consumer.connect(cred)
    consumer.review_and_activate("reviewer@acme")

    door.live_sessions.clear()  # the server forgot sess-1

    result = await consumer.execute("ticket.read", {}, cred, _ctx())

    assert result.ok and result.output == {"text": "strict-ok"}
    assert [m for m, _ in door.posts][-4:] == [
        "tools/call",  # refused: sess-1 is dead
        "initialize", "notifications/initialized",  # re-handshake mints sess-2
        "tools/call",  # retried on the fresh session
    ]
