"""Consume an external MCP server as an adapter (US-MCP-03, SEC-22).

Closes the loop: a Boltrig kernel consumes another Boltrig kernel's MCP face. The
consumed tools register as verbs; calls run the (external) chokepoint; the server
is inert until reviewed.
"""

import pytest

from boltrig.adapters.builtin.memory_tickets import build as build_tickets
from boltrig.adapters.mcp_consumer import McpConsumerAdapter
from boltrig.kernel import Kernel
from boltrig.models import GrantSet, InvocationContext, TenantPermissions
from boltrig.store import InMemoryStore

T = "acme"


async def _server_kernel() -> tuple[Kernel, str]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    k = Kernel(store)
    await k.register_adapter(T, build_tickets())
    token = k.mcp.issue_run_token(T, GrantSet.of(["ticket.*"]))
    return k, token


@pytest.mark.invariant("FR-MCP-03")
async def test_consume_external_mcp_server_as_verbs():
    server, token = await _server_kernel()
    # the consumer talks to the server's MCP face over an injected transport
    consumer = McpConsumerAdapter("ext-tickets", rpc=lambda req: server.mcp.handle(token, req))
    specs = await consumer.connect()
    # tools publish NAMESPACED under the adapter id, not verbatim
    assert {s.verb_id for s in specs} >= {
        "ext-tickets.ticket.create",
        "ext-tickets.ticket.read",
    }


@pytest.mark.invariant("SEC-22")
async def test_consumed_server_inert_until_reviewed():
    server, token = await _server_kernel()
    consumer = McpConsumerAdapter("ext-tickets", rpc=lambda req: server.mcp.handle(token, req))
    await consumer.connect()
    ctx = InvocationContext(tenant_id=T, grants=GrantSet.of(["*"]))

    inert = await consumer.execute("ext-tickets.ticket.create", {"title": "x"}, None, ctx)
    assert inert.ok is False  # pending review

    consumer.review_and_activate("alice@acme")
    live = await consumer.execute("ext-tickets.ticket.create", {"title": "x"}, None, ctx)
    # the prefixed verb maps back to the BARE tool name for tools/call
    assert live.ok and live.output["status"] == "open"  # via the external chokepoint
