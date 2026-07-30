"""Pinned Codex notification classes that invalidate quarantined evidence."""

from __future__ import annotations

from . import codex_protocol as wire
from .codex_runtime_config_toml import CODEX_MCP_SERVER_NAME

LIFECYCLE_METHODS = frozenset(
    {
        "error",
        "item/completed",
        "item/started",
        "thread/closed",
        "thread/started",
        "thread/tokenUsage/updated",
        "turn/completed",
        "turn/started",
        "warning",
    }
)
_INVALIDATION_METHODS = frozenset(
    {
        "app/list/updated",
        "configWarning",
        "externalAgentConfig/import/completed",
        "externalAgentConfig/import/progress",
        "fs/changed",
        "hook/completed",
        "hook/started",
        "mcpServer/oauthLogin/completed",
        "mcpServer/startupStatus/updated",
        "model/rerouted",
        "skills/changed",
        "thread/settings/updated",
    }
)


def is_runtime_invalidation(method: str) -> bool:
    """Return whether a notification invalidates quarantined phase evidence."""

    return method in _INVALIDATION_METHODS


def is_kernel_tools_mcp_startup_update(
    notification: wire.NotificationMessage,
) -> bool:
    """Accept only the admitted kernel MCP server's healthy startup updates."""

    if notification.method != "mcpServer/startupStatus/updated":
        return False
    params = notification.params.to_mapping()
    return (
        params.get("name") == CODEX_MCP_SERVER_NAME
        and params.get("status") in {"starting", "ready"}
    )


__all__ = [
    "LIFECYCLE_METHODS",
    "is_kernel_tools_mcp_startup_update",
    "is_runtime_invalidation",
]
