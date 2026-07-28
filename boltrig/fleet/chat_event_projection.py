"""Bound the tool events that reach a browser, at the chat SSE boundary (K-20).

Its own module because it is one rule with one long reason, and ``fleet/chat.py``
sits at a structural ratchet that a rule this self-contained should not consume.
"""

from __future__ import annotations

from typing import Any


def project_chat_event(event: dict[str, Any]) -> dict[str, Any]:
    """Bound the tool events before they reach the user-facing chat stream (K-20,
    US-CHAT-10).

    The run relay carries the FULL ``tool_call``/``tool_result`` payloads (``input``
    / ``output``) for the run canvas and the durable audit record (FR-EVT-01). The
    chat SSE, which a browser renders live, must NEVER carry the raw params or
    output of a verb: they can hold sensitive values or untrusted content. For
    those two event types this forwards only the bounded keys + summaries the UI
    needs to render a tool callout (``tool``/``call_id``/``args_summary`` and
    ``call_id``/``status``/``result_summary``); every other event passes through
    untouched, so message_start / text_delta / message_end / cancelled / hitl /
    question are unchanged."""
    etype = event.get("type")
    if etype == "tool_call":
        out: dict[str, Any] = {
            "type": "tool_call",
            "run_id": event.get("run_id"),
            "tool": event.get("tool") or event.get("verb"),
            "call_id": event.get("call_id"),
        }
        if "args_summary" in event:
            out["args_summary"] = event["args_summary"]
        return out
    if etype == "tool_result":
        out = {
            "type": "tool_result",
            "run_id": event.get("run_id"),
            "call_id": event.get("call_id"),
            "status": event.get("status"),
        }
        if "result_summary" in event:
            out["result_summary"] = event["result_summary"]
        return out
    return event
