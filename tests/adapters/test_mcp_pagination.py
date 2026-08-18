"""tools/list pagination on the consumer half (SPEC §11.6).

The defect these fence is silent rather than loud: one request WAS the whole of
discovery, so a paginating server's second page simply did not exist. Nothing
errored, nothing logged, and the tenant saw a truncated tool surface that looked
complete. Every test here therefore asserts either that a later page ARRIVES or
that a hostile pager is REFUSED - never merely that no exception was raised.
"""

from __future__ import annotations

import pytest

from boltrig.adapters.mcp_consumer import McpConsumerAdapter
from boltrig.adapters.mcp_discovery import McpDiscoveryInvalid


def _tool(name: str) -> dict:
    return {
        "name": name,
        "description": f"{name} description",
        "inputSchema": {"type": "object", "properties": {}},
    }


def _pager(pages: list[dict]):
    """A server that answers tools/list from a script, recording what it was sent."""
    sent: list[dict] = []

    async def rpc(request: dict) -> dict:
        sent.append(request)
        return {"jsonrpc": "2.0", "id": request.get("id"), "result": pages[len(sent) - 1]}

    return rpc, sent


@pytest.mark.invariant("FR-MCP-03")
async def test_discovery_follows_the_cursor_to_the_last_page():
    rpc, sent = _pager(
        [
            {"tools": [_tool("alpha"), _tool("beta")], "nextCursor": "page-2"},
            {"tools": [_tool("gamma")], "nextCursor": "page-3"},
            {"tools": [_tool("delta")]},
        ]
    )
    specs = await McpConsumerAdapter("ext", rpc=rpc).connect()
    assert {spec.verb_id for spec in specs} == {
        "ext.alpha",
        "ext.beta",
        "ext.gamma",
        "ext.delta",
    }
    # The first request carries no cursor; each later one carries the previous
    # page's token verbatim.
    assert [request["params"] for request in sent] == [
        {},
        {"cursor": "page-2"},
        {"cursor": "page-3"},
    ]


async def test_a_single_page_server_still_makes_exactly_one_request():
    """The regression fence: pagination must not cost an extra round trip
    against the servers that do not paginate, which is all of them today."""
    rpc, sent = _pager([{"tools": [_tool("alpha")]}])
    specs = await McpConsumerAdapter("ext", rpc=rpc).connect()
    assert {spec.verb_id for spec in specs} == {"ext.alpha"}
    assert len(sent) == 1


async def test_a_duplicate_tool_across_pages_is_refused():
    """Dedup was per-response, so the same tool on two pages would have produced
    two verbs from one operation."""
    rpc, _sent = _pager(
        [
            {"tools": [_tool("alpha")], "nextCursor": "page-2"},
            {"tools": [_tool("alpha")]},
        ]
    )
    with pytest.raises(McpDiscoveryInvalid):
        await McpConsumerAdapter("ext", rpc=rpc).connect()


async def test_the_snapshot_cap_counts_the_running_total(monkeypatch):
    """A per-response cap is no cap at all once a server can paginate: three
    pages of two are six tools however small each page looks."""
    monkeypatch.setattr("boltrig.adapters.mcp_discovery.MCP_MAX_TOOL_SNAPSHOT", 3)
    rpc, _sent = _pager(
        [
            {"tools": [_tool("a"), _tool("b")], "nextCursor": "page-2"},
            {"tools": [_tool("c"), _tool("d")]},
        ]
    )
    with pytest.raises(McpDiscoveryInvalid):
        await McpConsumerAdapter("ext", rpc=rpc).connect()


async def test_a_repeating_cursor_is_refused_rather_than_looping():
    """A server that hands back its own cursor forever is an infinite loop
    inside the probe timeout, which presents as a hang, not a refusal."""

    async def rpc(request: dict) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": {"tools": [_tool("alpha")], "nextCursor": "same"},
        }

    with pytest.raises(McpDiscoveryInvalid):
        await McpConsumerAdapter("ext", rpc=rpc).connect()


async def test_the_page_ceiling_bounds_a_server_that_never_ends(monkeypatch):
    """Distinct cursors defeat the repeat check, so the ceiling is the backstop."""
    monkeypatch.setattr("boltrig.adapters.mcp_consumer.MCP_MAX_TOOL_PAGES", 3)
    counter = {"n": 0}

    async def rpc(request: dict) -> dict:
        counter["n"] += 1
        return {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": {
                "tools": [_tool(f"tool_{counter['n']}")],
                "nextCursor": f"page-{counter['n']}",
            },
        }

    with pytest.raises(McpDiscoveryInvalid):
        await McpConsumerAdapter("ext", rpc=rpc).connect()
    assert counter["n"] == 3


@pytest.mark.parametrize("cursor", [123, "", {"a": 1}, [], "x" * 4096])
async def test_a_malformed_cursor_is_refused_not_read_as_the_last_page(cursor):
    """Treating an unusable cursor as end-of-list would restore the original
    defect exactly - a truncated surface, silently."""
    rpc, _sent = _pager([{"tools": [_tool("alpha")], "nextCursor": cursor}])
    with pytest.raises(McpDiscoveryInvalid):
        await McpConsumerAdapter("ext", rpc=rpc).connect()
