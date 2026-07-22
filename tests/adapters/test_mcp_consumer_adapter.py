"""MCP consumer adapter: transport failures are typed, standard content maps."""

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
