"""Durable external-MCP lifecycle, discovery snapshots, and probe evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

MCP_SERVER_STATES = ("inactive", "active", "retired")
MCP_PROBE_OUTCOMES = ("succeeded", "failed")
MCP_PROBE_FAILURE_CODES = (
    "credential_unavailable",
    "egress_denied",
    "transport_unavailable",
    "protocol_invalid",
    "discovery_invalid",
    "unexpected_failure",
)
MCP_PROBE_RECEIPTS_PER_SERVER = 20
MCP_MAX_RETURNED_PROBE_RECEIPTS = 100
# A REAL adapter exceeds 500. Measured on the beelink 2026-07-30: the `opbox`
# consumer publishes 633 verbs (verb_bindings.target_ref='opbox'), so this cap
# refused a legitimately-registered server. The DoS bound that actually matters is
# MCP_MAX_TOOL_SNAPSHOT_BYTES below - a count cap only bounds the row count, and
# 2MB already bounds the payload whatever the count. Kept as a sanity ceiling, set
# above any plausible real registry rather than below the one we ship.
MCP_MAX_TOOL_SNAPSHOT = 5000
# Pagination bounds (SPEC §11.6). MCP_MAX_TOOL_PAGES is deliberately the
# snapshot cap divided by a conventional page size rather than a round number:
# a server that needs more pages than that to deliver 5000 tools is paginating
# so finely that the round trips, not the tools, are the problem. The cursor is
# untrusted text this process echoes straight back to the server, so it carries
# its own length bound.
MCP_MAX_TOOL_PAGES = 50
MCP_MAX_CURSOR_BYTES = 2 * 1024
MCP_MAX_TOOL_DESCRIPTION_BYTES = 8 * 1024
MCP_MAX_TOOL_SCHEMA_BYTES = 256 * 1024
MCP_MAX_TOOL_SNAPSHOT_BYTES = 2 * 1024 * 1024
MCP_MAX_TOOL_SCHEMA_DEPTH = 32


def _aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _schema_depth(value: Any, depth: int = 0) -> int:
    if depth > MCP_MAX_TOOL_SCHEMA_DEPTH:
        return depth
    if isinstance(value, dict):
        return max(
            (depth, *(_schema_depth(item, depth + 1) for item in value.values()))
        )
    if isinstance(value, list):
        return max(
            (depth, *(_schema_depth(item, depth + 1) for item in value))
        )
    return depth


def _json_size(value: Any, field_name: str) -> int:
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be JSON serializable") from exc
    return len(encoded)


def validate_mcp_tool_snapshot(tools: tuple["McpToolSnapshot", ...]) -> None:
    if len(tools) > MCP_MAX_TOOL_SNAPSHOT:
        raise ValueError("MCP tool snapshot is out of bounds")
    if (
        _json_size(
            [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "consequence": tool.consequence,
                    "input_schema": tool.input_schema,
                    "output_schema": tool.output_schema,
                }
                for tool in tools
            ],
            "last_known_tools",
        )
        > MCP_MAX_TOOL_SNAPSHOT_BYTES
    ):
        raise ValueError("MCP tool snapshot payload is out of bounds")


@dataclass(frozen=True)
class McpToolSnapshot:
    """Content-safe tool contract captured by an explicit discovery."""

    name: str
    description: str
    consequence: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    # The canonical capability this tool CLAIMS to implement (SPEC §5 level 1).
    # Optional and defaulted so a snapshot persisted before this existed still
    # loads: the strict key check in the store codec accepts both shapes.
    implements: str | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("MCP tool snapshot name is required")
        if self.implements is not None and (
            not self.implements or "@" in self.implements
        ):
            raise ValueError("MCP tool capability claim must be an unpinned id")
        if self.consequence not in {"low", "high"}:
            raise ValueError("MCP tool consequence must be low or high")
        if len(self.description.encode("utf-8")) > MCP_MAX_TOOL_DESCRIPTION_BYTES:
            raise ValueError("MCP tool description is out of bounds")
        for field_name, schema in (
            ("input_schema", self.input_schema),
            ("output_schema", self.output_schema),
        ):
            if not isinstance(schema, dict):
                raise ValueError(f"MCP tool {field_name} must be an object")
            if _schema_depth(schema) > MCP_MAX_TOOL_SCHEMA_DEPTH:
                raise ValueError(f"MCP tool {field_name} nesting is out of bounds")
            if _json_size(schema, field_name) > MCP_MAX_TOOL_SCHEMA_BYTES:
                raise ValueError(f"MCP tool {field_name} is out of bounds")


@dataclass(frozen=True)
class McpProbeReceipt:
    """Content-free outcome evidence for one explicit server-side probe."""

    tenant_id: str
    server_id: str
    probe_id: str
    outcome: str
    failure_code: str | None
    observed_at: datetime
    tool_count: int

    def __post_init__(self) -> None:
        if not self.tenant_id or not self.server_id or not self.probe_id:
            raise ValueError("MCP probe identity fields are required")
        if self.outcome not in MCP_PROBE_OUTCOMES:
            raise ValueError("invalid MCP probe outcome")
        if self.outcome == "succeeded" and self.failure_code is not None:
            raise ValueError("successful MCP probe cannot carry a failure code")
        if (
            self.outcome == "failed"
            and self.failure_code not in MCP_PROBE_FAILURE_CODES
        ):
            raise ValueError("failed MCP probe requires a known failure code")
        if not 0 <= self.tool_count <= MCP_MAX_TOOL_SNAPSHOT:
            raise ValueError("MCP probe tool count is out of bounds")
        _aware(self.observed_at, "observed_at")


@dataclass(frozen=True)
class McpServerLifecycle:
    """Durable state and last successful discovery for one consumed server."""

    tenant_id: str
    server_id: str
    state: str
    config_revision: int = 1
    last_known_tools: tuple[McpToolSnapshot, ...] = field(default_factory=tuple)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    retired_at: datetime | None = None
    tools_observed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.tenant_id or not self.server_id:
            raise ValueError("MCP server lifecycle identity fields are required")
        if self.state not in MCP_SERVER_STATES:
            raise ValueError("invalid MCP server lifecycle state")
        if type(self.config_revision) is not int or self.config_revision < 1:
            raise ValueError("invalid MCP server config revision")
        validate_mcp_tool_snapshot(self.last_known_tools)
        for name, value in (
            ("created_at", self.created_at),
            ("updated_at", self.updated_at),
            ("retired_at", self.retired_at),
            ("tools_observed_at", self.tools_observed_at),
        ):
            if value is not None:
                _aware(value, name)
