"""Content-free terminal and diagnostic values for the Codex runtime actor."""

from __future__ import annotations

from dataclasses import dataclass

from . import codex_protocol as wire
from .codex_runtime_event_state import CodexRuntimeProtocolError


@dataclass(frozen=True)
class CodexRuntimeTerminal:
    category: str
    message: str

    def exception(self) -> Exception:
        if self.category == "protocol":
            return CodexRuntimeProtocolError(self.message)
        return RuntimeError(self.message)


def redacted_notification_marker(notification: wire.NotificationMessage) -> str:
    """Return only config-derived MCP state or the notification method."""
    if notification.method == "mcpServer/startupStatus/updated":
        try:
            params = notification.params.to_mapping()
            return f"name={params.get('name')!r} status={params.get('status')!r}"
        except Exception:
            return "unparseable"
    return "method-only"
