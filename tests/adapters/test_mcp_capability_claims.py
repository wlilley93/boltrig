"""A consumed MCP server may CLAIM a canonical capability (SPEC §5, level 1).

The claim is third-party text: a remote server asserting something about a
vocabulary it does not own. That is safe only because of where it lands - a
PROPOSED binding routes nothing, governs nothing and is invisible to the
connection projection until a human approves it. These tests pin the claim
travelling end to end AND the fact that it confers nothing on arrival, because
the second half is the one that makes the first half safe.
"""

from __future__ import annotations

import pytest

from boltrig.adapters.mcp_consumer import McpConsumerAdapter
from boltrig.kernel import Kernel
from boltrig.models import GrantSet, TenantPermissions
from boltrig.store import InMemoryStore

T = "acme"


def _tool(name: str, **extra) -> dict:
    return {
        "name": name,
        "description": f"{name} description",
        "inputSchema": {"type": "object", "properties": {}},
        **extra,
    }


def _rpc(tools: list[dict]):
    async def rpc(request: dict) -> dict:
        return {"jsonrpc": "2.0", "id": request.get("id"), "result": {"tools": tools}}

    return rpc


async def _register(tools: list[dict]) -> tuple[Kernel, InMemoryStore]:
    store = InMemoryStore()
    store.set_tenant_permissions(TenantPermissions(T, GrantSet.of(["*"])))
    kernel = Kernel(store)
    consumer = McpConsumerAdapter("ext", rpc=_rpc(tools))
    await consumer.connect()
    await kernel.register_adapter(T, consumer)
    return kernel, store


async def test_a_declared_capability_reaches_the_registry_as_a_proposed_binding():
    _, store = await _register(
        [_tool("contact.search", implements="crm.contact.search", consequence="low")]
    )
    bindings = await store.list_capability_bindings(T, "crm.contact.search")
    assert [(b.status, b.created_from, b.source_operation_id) for b in bindings] == [
        ("proposed", "declared", "ext.contact.search")
    ]


async def test_a_proposed_claim_routes_nothing():
    """The whole safety argument: a stranger's claim on `matter.open` must not
    make `matter.open` callable."""
    from boltrig.kernel.routing import resolve_execution_plan
    from boltrig.models import BindingNotFound

    _, store = await _register([_tool("open", implements="matter.open")])
    with pytest.raises(BindingNotFound):
        await resolve_execution_plan(store, T, "matter.open")


async def test_a_proposed_claim_confers_no_approval_reach():
    """... and it cannot widen who may answer a held call either."""
    from boltrig.kernel.routing import governed_aliases

    _, store = await _register([_tool("open", implements="matter.open")])
    assert await governed_aliases(store, T, "matter.open") == ("matter.open",)


async def test_a_tool_that_claims_nothing_creates_no_binding():
    _, store = await _register([_tool("contact.search")])
    assert await store.list_capability_bindings(T) == []


@pytest.mark.parametrize(
    "claim",
    ["crm.contact.search@1", "not a capability", "", 17, {"a": 1}, "x" * 300],
)
async def test_a_malformed_or_pinned_claim_is_dropped_not_honoured(claim):
    """A pinned claim names a version this side has not agreed to, and reading it
    as the one it HAS agreed to would invent the agreement. Everything unusable
    is dropped rather than refused, because the tool itself is still publishable
    - only its claim is not."""
    _, store = await _register([_tool("contact.search", implements=claim)])
    assert await store.list_capability_bindings(T) == []


async def test_the_tool_itself_still_publishes_when_its_claim_is_dropped():
    kernel, store = await _register(
        [_tool("contact.search", implements="crm.contact.search@9")]
    )
    assert await store.get_verb(T, "ext.contact.search") is not None
