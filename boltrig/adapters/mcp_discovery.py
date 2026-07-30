"""Pure, bounded conversion of an untrusted MCP tools/list response."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from boltrig.models import MCP_MAX_TOOL_SNAPSHOT, McpToolSnapshot
from boltrig.models.mcp_lifecycle import validate_mcp_tool_snapshot

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


def snapshot_from_response(
    adapter_id: str,
    response: Any,
    consequence_for: Callable[[dict[str, Any]], str],
) -> tuple[McpToolSnapshot, ...]:
    if not isinstance(response, dict):
        raise McpProtocolInvalid
    result = response.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
        raise McpProtocolInvalid
    tools = result["tools"]
    if len(tools) > MCP_MAX_TOOL_SNAPSHOT:
        raise McpDiscoveryInvalid
    snapshot: list[McpToolSnapshot] = []
    seen: set[str] = set()
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
        if not isinstance(input_schema, dict) or not isinstance(
            output_schema, dict
        ):
            raise McpDiscoveryInvalid
        try:
            snapshot.append(
                McpToolSnapshot(
                    name=name,
                    description=str(tool.get("description") or ""),
                    consequence=consequence_for(tool),
                    input_schema=input_schema,
                    output_schema=output_schema,
                )
            )
        except ValueError as exc:
            raise McpDiscoveryInvalid from exc
    discovered = tuple(sorted(snapshot, key=lambda item: item.name))
    try:
        validate_mcp_tool_snapshot(discovered)
    except ValueError as exc:
        raise McpDiscoveryInvalid from exc
    return discovered

