"""Pure, bounded conversion of an untrusted MCP tools/list response."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from boltrig.models import MCP_MAX_TOOL_SNAPSHOT, McpToolSnapshot
from boltrig.models.mcp_lifecycle import (
    MCP_MAX_CURSOR_BYTES,
    validate_mcp_tool_snapshot,
)

from .mcp_tool_policy import external_description

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
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw:
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
) -> tuple[list[McpToolSnapshot], str | None]:
    """Parse one page, sharing ``seen`` so a duplicate ACROSS pages still fails.

    ``accumulated`` is what previous pages already yielded: the snapshot cap is
    tested against the running total, because a per-response cap is no cap at
    all once a server can paginate.
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
    for tool in tools:
        if not isinstance(tool, dict):
            raise McpDiscoveryInvalid
        name = str(tool.get("name") or "")
        if not name or not _TOOL_VERB_ID.fullmatch(f"{adapter_id}.{name}"):
            log.warning(
                "mcp server '%s' exposed a tool that was skipped because its "
                "name is not publishable",
                adapter_id,
            )
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
                )
            )
        except ValueError as exc:
            raise McpDiscoveryInvalid from exc
    return snapshot, _next_cursor(result)
