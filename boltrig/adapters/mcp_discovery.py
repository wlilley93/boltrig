"""Pure, bounded conversion of an untrusted MCP tools/list response."""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from boltrig.models import MCP_MAX_TOOL_SNAPSHOT, McpToolSnapshot
from boltrig.models.mcp_lifecycle import (
    MCP_MAX_CURSOR_BYTES,
    MCP_MAX_TOOL_PAGES,
    validate_mcp_tool_snapshot,
)

from .mcp_tool_policy import external_description, implements_hint

_TOOL_VERB_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
log = logging.getLogger("boltrig.adapters.mcp_consumer")


class McpProtocolInvalid(Exception):
    pass


class McpDiscoveryInvalid(Exception):
    pass


@dataclass(frozen=True)
class McpProbeResult:
    """Content-free result from one bounded discovery attempt."""

    succeeded: bool
    failure_code: str | None
    tools: tuple[McpToolSnapshot, ...]


async def discover_pages(
    call: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    adapter_id: str,
    consequence_for: Callable[[dict[str, Any]], str],
) -> tuple[McpToolSnapshot, ...]:
    """Follow ``tools/list`` to its last page over ONE caller-owned connection.

    The loop lives here rather than in the consumer because every bound it obeys
    belongs to the parser: the accumulated scan count, the cursor validation and
    the dedup set are all page-parser state, and splitting them across two
    modules is how a cap ends up applied per page.

    Four bounds, each answering a way a remote server could turn the loop into a
    weapon: a page ceiling, the accumulated SCAN cap, the cursor length bound,
    and a repeat-cursor check - a server that hands back its own cursor forever
    is otherwise an infinite loop inside the probe timeout, which presents as a
    hang rather than a refusal.
    """
    tools: list[McpToolSnapshot] = []
    seen: set[str] = set()
    cursors: set[str] = set()
    cursor: str | None = None
    scanned = 0
    for _page in range(MCP_MAX_TOOL_PAGES):
        params: dict[str, Any] = {} if cursor is None else {"cursor": cursor}
        response = await call(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": params}
        )
        page, cursor, page_size = page_from_response(
            adapter_id, response, consequence_for, seen, accumulated=scanned
        )
        tools.extend(page)
        scanned += page_size
        if cursor is None:
            return finalise_snapshot(tools)
        if cursor in cursors:
            raise McpDiscoveryInvalid
        cursors.add(cursor)
    raise McpDiscoveryInvalid


def finalise_snapshot(tools: list[McpToolSnapshot]) -> tuple[McpToolSnapshot, ...]:
    """Sort and re-validate an assembled snapshot.

    The byte cap runs HERE, on everything collected, because a per-page check is
    exactly what pagination walks around.
    """
    discovered = tuple(sorted(tools, key=lambda item: item.name))
    try:
        validate_mcp_tool_snapshot(discovered)
    except ValueError as exc:
        raise McpDiscoveryInvalid from exc
    return discovered


def _next_cursor(result: dict[str, Any]) -> str | None:
    """The server's continuation token, or None at the last page.

    Anything that is not a bounded non-empty string is a protocol violation
    rather than a quiet end-of-list: silently treating a malformed cursor as
    "no more pages" is how the original single-request bug would come back
    wearing a loop.
    """
    raw = result.get("nextCursor")
    if not raw:
        # Absent, null, "", false, 0. The old single-request path ignored the key
        # entirely, and "" is a common end-of-list convention for a server built
        # over a generic pager - refusing it would have turned discovery of a
        # perfectly good single-page server into a content-free failure the
        # operator could not diagnose.
        return None
    if not isinstance(raw, str):
        raise McpDiscoveryInvalid
    if len(raw.encode("utf-8")) > MCP_MAX_CURSOR_BYTES:
        raise McpDiscoveryInvalid
    return raw


def page_from_response(
    adapter_id: str,
    response: Any,
    consequence_for: Callable[[dict[str, Any]], str],
    seen: set[str],
    *,
    accumulated: int = 0,
) -> tuple[list[McpToolSnapshot], str | None, int]:
    """Parse one page, sharing ``seen`` so a duplicate ACROSS pages still fails.

    ``accumulated`` is what previous pages already SCANNED, not what they
    yielded, and the difference is the whole bound. A tool whose name cannot
    publish is skipped, so counting survivors let a server send 50 pages of 5000
    unpublishable names while the running total stayed at zero - 250,000 parses
    and, before this, 250,000 log lines. The third return value is that scanned
    count, so the caller can hold the total the check is made against.
    """
    if not isinstance(response, dict):
        raise McpProtocolInvalid
    result = response.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
        raise McpProtocolInvalid
    tools = result["tools"]
    if accumulated + len(tools) > MCP_MAX_TOOL_SNAPSHOT:
        raise McpDiscoveryInvalid
    snapshot: list[McpToolSnapshot] = []
    skipped = 0
    for tool in tools:
        if not isinstance(tool, dict):
            raise McpDiscoveryInvalid
        name = str(tool.get("name") or "")
        if not name or not _TOOL_VERB_ID.fullmatch(f"{adapter_id}.{name}"):
            # Counted and reported ONCE per page. One line per skipped tool was
            # bounded by a single response before pagination; across a page loop
            # it is an unthrottled write amplifier a remote server controls.
            skipped += 1
            continue
        if name in seen:
            raise McpDiscoveryInvalid
        seen.add(name)
        input_schema = tool.get("inputSchema", {})
        output_schema = tool.get("outputSchema") or {}
        if not isinstance(input_schema, dict) or not isinstance(output_schema, dict):
            raise McpDiscoveryInvalid
        try:
            snapshot.append(
                McpToolSnapshot(
                    name=name,
                    description=external_description(str(tool.get("description") or "")),
                    consequence=consequence_for(tool),
                    input_schema=input_schema,
                    output_schema=output_schema,
                    implements=implements_hint(tool),
                )
            )
        except ValueError as exc:
            raise McpDiscoveryInvalid from exc
    if skipped:
        log.warning(
            "mcp server '%s' offered %d tool(s) skipped because their names are "
            "not publishable",
            adapter_id,
            skipped,
        )
    return snapshot, _next_cursor(result), len(tools)
