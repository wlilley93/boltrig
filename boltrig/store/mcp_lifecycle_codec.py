"""Validation and row codecs for durable external-MCP lifecycle state."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import json
from typing import Any

from boltrig.models import (
    MCP_SERVER_STATES,
    McpProbeReceipt,
    McpServerLifecycle,
    McpToolSnapshot,
)

MCP_CONSUMER_MODULE = "boltrig.adapters.mcp_consumer"
_TRANSITIONS = {
    "inactive": frozenset({"active", "retired"}),
    "active": frozenset({"inactive"}),
    "retired": frozenset({"inactive"}),
}
_TOOL_KEYS = frozenset(
    {"name", "description", "consequence", "input_schema", "output_schema"}
)


def aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def tool_payload(tools: tuple[McpToolSnapshot, ...]) -> list[dict[str, Any]]:
    validated = McpServerLifecycle(
        tenant_id="_validation",
        server_id="_validation",
        state="inactive",
        last_known_tools=tuple(tools),
    )
    encoded = [
        {
            "name": tool.name,
            "description": tool.description,
            "consequence": tool.consequence,
            "input_schema": tool.input_schema,
            "output_schema": tool.output_schema,
        }
        for tool in validated.last_known_tools
    ]
    return json.loads(
        json.dumps(encoded, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )


def tools(value: Any) -> tuple[McpToolSnapshot, ...]:
    if not isinstance(value, list):
        raise ValueError("persisted MCP tool snapshot must be an array")
    if any(not isinstance(item, dict) for item in value):
        raise ValueError("persisted MCP tool snapshot entries must be objects")
    if any(frozenset(item) != _TOOL_KEYS for item in value):
        raise ValueError("persisted MCP tool snapshot fields are invalid")
    return tuple(
        McpToolSnapshot(
            name=item["name"],
            description=item["description"],
            consequence=item["consequence"],
            input_schema=item["input_schema"],
            output_schema=item["output_schema"],
        )
        for item in value
    )


def lifecycle(row: Any) -> McpServerLifecycle | None:
    if row is None:
        return None
    return McpServerLifecycle(
        tenant_id=row["tenant_id"],
        server_id=row["id"],
        state=row["status"],
        config_revision=row["config_revision"],
        last_known_tools=tools(row["last_known_tools"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        retired_at=row["retired_at"],
        tools_observed_at=row["tools_observed_at"],
    )


def receipt(row: Any) -> McpProbeReceipt | None:
    if row is None:
        return None
    return McpProbeReceipt(
        tenant_id=row["tenant_id"],
        server_id=row["server_id"],
        probe_id=row["probe_id"],
        outcome=row["outcome"],
        failure_code=row["failure_code"],
        observed_at=row["observed_at"],
        tool_count=row["tool_count"],
    )


def copy_lifecycle(value: McpServerLifecycle) -> McpServerLifecycle:
    payload = tool_payload(value.last_known_tools)
    return replace(value, last_known_tools=tools(payload))


def validate_transition(
    *,
    existing_state: str | None,
    expected_state: str | None,
    new_state: str,
) -> bool:
    if new_state not in MCP_SERVER_STATES:
        raise ValueError("invalid MCP server lifecycle state")
    if existing_state is None:
        if expected_state is not None:
            return False
        if new_state != "inactive":
            raise ValueError("an MCP lifecycle must be created inactive")
        return True
    if expected_state != existing_state:
        return False
    if new_state == existing_state:
        return True
    if new_state not in _TRANSITIONS[existing_state]:
        raise ValueError(f"invalid MCP lifecycle transition {existing_state}->{new_state}")
    return True


def validate_snapshot(
    last_known_tools: tuple[McpToolSnapshot, ...] | None,
    tools_observed_at: datetime | None,
) -> list[dict[str, Any]] | None:
    if (last_known_tools is None) != (tools_observed_at is None):
        raise ValueError("MCP tool snapshot and observation time must be supplied together")
    if tools_observed_at is not None:
        aware(tools_observed_at, "tools_observed_at")
    return None if last_known_tools is None else tool_payload(last_known_tools)


def validate_probe_snapshot(
    probe: McpProbeReceipt,
    last_known_tools: tuple[McpToolSnapshot, ...] | None,
) -> list[dict[str, Any]] | None:
    if probe.outcome == "failed":
        if last_known_tools is not None or probe.tool_count != 0:
            raise ValueError("a failed MCP probe cannot carry a tool snapshot")
        return None
    if last_known_tools is None:
        raise ValueError("a successful MCP probe requires a tool snapshot")
    payload = tool_payload(last_known_tools)
    if len(payload) != probe.tool_count:
        raise ValueError("MCP probe tool count does not match its snapshot")
    return payload


__all__ = [
    "MCP_CONSUMER_MODULE",
    "aware",
    "copy_lifecycle",
    "lifecycle",
    "receipt",
    "tools",
    "validate_probe_snapshot",
    "validate_snapshot",
    "validate_transition",
]
