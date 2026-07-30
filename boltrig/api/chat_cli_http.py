"""Bounded HTTP response interpretation for the terminal chat client."""

from __future__ import annotations

import json
from typing import Any


def _json_object(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def queued_chat_event(status: int, body: bytes) -> dict[str, Any] | None:
    """Map only the kernel's accepted-steer 202 body to a terminal event."""
    payload = _json_object(body)
    if status != 202 or payload.get("status") != "queued":
        return None
    return {
        "type": "queued",
        "conversation_id": payload.get("conversation_id"),
        "message_id": payload.get("message_id"),
        "run_id": payload.get("run_id"),
    }


def http_error(status: int, body: bytes) -> str:
    """A one-line, user-facing HTTP failure. The token is never part of it."""
    payload = _json_object(body)
    reason = payload.get("reason") or payload.get("error")
    if status in (401, 403):
        return (
            f"authentication failed (HTTP {status}) - check the token "
            "(--token / BOLTRIG_CLI_TOKEN / ~/.config/boltrig/cli.toml)"
        )
    return f"request failed (HTTP {status}){f': {reason}' if reason else ''}"
