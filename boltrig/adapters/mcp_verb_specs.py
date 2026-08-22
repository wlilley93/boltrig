"""One consumed MCP tool, as the kernel registry sees it.

Pure: a vetted snapshot row in, a ``VerbSpec`` out. Extracted from
``mcp_consumer`` so the adapter file keeps its size floor without losing the
history below, which is the only reason the output schema is shaped this way.
"""

from __future__ import annotations

from boltrig.adapters.base import VerbSpec
from boltrig.models import McpToolSnapshot

from .mcp_tool_policy import external_description


def spec_from_snapshot(adapter_id: str, tool: McpToolSnapshot) -> VerbSpec:
    """Render one snapshot row as the verb the kernel will register."""
    return VerbSpec(
        verb_id=f"{adapter_id}.{tool.name}",
        noun_id=adapter_id,  # one noun per consumed server (opbox.*)
        input_schema=tool.input_schema,
        # An MCP tool returns arbitrary JSON - an array, a string and a number
        # are all legal results. Asserting `{"type": "object"}` here rejected
        # every list-shaped tool at OUTPUT validation with `invalid output for
        # '<verb>'`, long after the call had already succeeded downstream:
        # opbox's `list_matters` really did return the caller's matters and the
        # kernel then threw the answer away. Honour the server's own
        # `outputSchema` when it declares one, otherwise accept any JSON rather
        # than inventing a constraint the protocol does not make.
        output_schema=tool.output_schema,
        description=external_description(tool.description),
        consequence=tool.consequence,
        # The server's CLAIM, which the registry records as a PROPOSED binding
        # that routes nothing until a human approves it
        # (mcp_tool_policy.implements_hint).
        implements=tool.implements,
    )
