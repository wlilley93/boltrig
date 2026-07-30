"""Closed, browser-safe projection of the internal run-event relay.

The durable relay is an internal integration surface.  It can contain richer
tool payloads and runtime-specific frames that must never become an accidental
browser API merely because they were published on the same run.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class _UnsupportedEvent(ValueError):
    """An internal frame cannot be represented by the public chat contract."""


def _required_text(event: dict[str, Any], key: str) -> str:
    value = event.get(key)
    if not isinstance(value, str):
        raise _UnsupportedEvent(key)
    return value


def _optional_text(event: dict[str, Any], key: str) -> str | None:
    value = event.get(key)
    return value if isinstance(value, str) else None


def _optional_bool(event: dict[str, Any], key: str) -> bool | None:
    value = event.get(key)
    return value if isinstance(value, bool) else None


def _optional_int(event: dict[str, Any], key: str) -> int | None:
    value = event.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, str)]


def _put(out: dict[str, Any], key: str, value: Any) -> None:
    if value is not None:
        out[key] = value


def _simple(
    event: dict[str, Any],
    *,
    required: tuple[str, ...] = (),
    optional: tuple[str, ...] = (),
) -> dict[str, Any]:
    out = {"type": _required_text(event, "type")}
    for key in required:
        out[key] = _required_text(event, key)
    for key in optional:
        _put(out, key, _optional_text(event, key))
    return out


def _text_delta(event: dict[str, Any]) -> dict[str, Any]:
    out = _simple(event, required=("delta",))
    _put(out, "degraded", _optional_bool(event, "degraded"))
    return out


def _tool_call(event: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "type": "tool_call",
        "run_id": _optional_text(event, "run_id"),
        "tool": _optional_text(event, "tool") or _optional_text(event, "verb"),
        "call_id": _optional_text(event, "call_id"),
    }
    summary = event.get("args_summary")
    if isinstance(summary, dict):
        safe_summary: dict[str, Any] = {"keys": _text_list(summary.get("keys"))}
        count = _optional_int(summary, "count")
        _put(safe_summary, "count", count)
        out["args_summary"] = safe_summary
    return out


def _tool_result(event: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "type": "tool_result",
        "run_id": _optional_text(event, "run_id"),
        "call_id": _optional_text(event, "call_id"),
        "status": _required_text(event, "status"),
    }
    summary = event.get("result_summary")
    if isinstance(summary, dict):
        safe_summary: dict[str, Any] = {"keys": _text_list(summary.get("keys"))}
        _put(safe_summary, "status", _optional_text(summary, "status"))
        out["result_summary"] = safe_summary
    return out


def _spawn_rule(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    rule_id = value.get("id")
    capability = value.get("capability")
    priority = value.get("priority")
    if (
        not isinstance(rule_id, str)
        or not isinstance(capability, str)
        or not isinstance(priority, int)
        or isinstance(priority, bool)
    ):
        return None
    out: dict[str, Any] = {
        "id": rule_id,
        "priority": priority,
        "matched_intent_tags": _text_list(value.get("matched_intent_tags")),
        "capability": capability,
        "skills_added": _text_list(value.get("skills_added")),
        "max_depth": None,
    }
    max_depth = value.get("max_depth")
    if max_depth is None or (isinstance(max_depth, int) and not isinstance(max_depth, bool)):
        out["max_depth"] = max_depth
    return out


def _familiar_genotype(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    out: dict[str, Any] = {}
    for key in ("source", "body", "voice_id"):
        if value.get(key) is None and key == "voice_id":
            out[key] = None
        else:
            _put(out, key, _optional_text(value, key))
    _put(out, "seed", _optional_int(value, "seed"))
    for key in ("palette", "markings", "accessories"):
        if key in value:
            out[key] = _text_list(value.get(key))
    return out


def _subagent(event: dict[str, Any]) -> dict[str, Any]:
    out = _simple(
        event,
        required=("child_run_id", "task"),
        optional=("name", "role", "color"),
    )
    out["skills"] = _text_list(event.get("skills"))
    _put(out, "step_count", _optional_int(event, "step_count"))
    _put(out, "spawn_rule", _spawn_rule(event.get("spawn_rule")))
    _put(
        out,
        "familiar_genotype",
        _familiar_genotype(event.get("familiar_genotype")),
    )
    return out


def _subagent_end(event: dict[str, Any]) -> dict[str, Any]:
    status = _required_text(event, "status")
    if status not in {"ok", "degraded", "error"}:
        raise _UnsupportedEvent("status")
    return {
        "type": "subagent_end",
        "child_run_id": _required_text(event, "child_run_id"),
        "status": status,
    }


def _hitl(event: dict[str, Any]) -> dict[str, Any]:
    out = _simple(
        event,
        required=("hitl_request_id",),
        optional=(
            "kind",
            "question",
            "verb",
            "call_id",
            "requested_by",
            "secure_purpose",
            "purpose",
        ),
    )
    if "options" in event:
        out["options"] = _text_list(event.get("options"))
    _put(out, "secure", _optional_bool(event, "secure"))
    return out


def _question(event: dict[str, Any]) -> dict[str, Any]:
    out = _simple(
        event,
        required=("question_id", "prompt"),
        optional=("run_id", "purpose"),
    )
    if "choices" in event:
        out["choices"] = _text_list(event.get("choices"))
    _put(out, "secure", _optional_bool(event, "secure"))
    return out


def _workflow_step(event: dict[str, Any]) -> dict[str, Any]:
    status = _required_text(event, "status")
    if status not in {"running", "ok", "failed", "skipped", "paused", "error"}:
        raise _UnsupportedEvent("status")
    return {
        "type": "workflow_step",
        "step_id": _required_text(event, "step_id"),
        "action": _required_text(event, "action"),
        "status": status,
    }


def _workflow_run(event: dict[str, Any]) -> dict[str, Any]:
    status = _required_text(event, "status")
    if status not in {"completed", "failed", "paused"}:
        raise _UnsupportedEvent("status")
    return {
        "type": "workflow_run",
        "run_id": _required_text(event, "run_id"),
        "workflow_id": _required_text(event, "workflow_id"),
        "status": status,
    }


def _model_routing(event: dict[str, Any]) -> dict[str, Any]:
    out = _simple(
        event,
        required=(
            "run_id",
            "selected_profile_id",
            "routing_class",
            "reason",
        ),
        optional=("requested_profile_id",),
    )
    overridden = _optional_bool(event, "overridden")
    if overridden is None:
        raise _UnsupportedEvent("overridden")
    out["overridden"] = overridden
    return out


def _artifact(event: dict[str, Any]) -> dict[str, Any]:
    out = _simple(
        event,
        required=("artifact_id", "name", "media_type"),
        optional=("run_id",),
    )
    size = _optional_int(event, "size")
    if size is None or size < 0:
        raise _UnsupportedEvent("size")
    out["size"] = size
    return out


def _artifact_rejected(event: dict[str, Any]) -> dict[str, Any]:
    count = _optional_int(event, "count")
    if count is None or count < 1:
        raise _UnsupportedEvent("count")
    out: dict[str, Any] = {"type": "artifact_rejected", "count": count}
    _put(out, "run_id", _optional_text(event, "run_id"))
    return out


def _steer(event: dict[str, Any]) -> dict[str, Any]:
    return _simple(
        event,
        optional=("run_id", "conversation_id", "message_id"),
    )


_Projector = Callable[[dict[str, Any]], dict[str, Any]]
_PROJECTORS: dict[str, _Projector] = {
    "message_start": lambda event: _simple(event, required=("run_id", "conversation_id")),
    "text_delta": _text_delta,
    "reasoning_delta": lambda event: _simple(event, required=("delta",)),
    "tool_call": _tool_call,
    "tool_result": _tool_result,
    "subagent": _subagent,
    "subagent_end": _subagent_end,
    "hitl": _hitl,
    "question": _question,
    "heartbeat": lambda event: _simple(event, optional=("run_id",)),
    "message_end": lambda event: _simple(event, required=("run_id",)),
    "cancelled": lambda event: _simple(event, required=("run_id",)),
    "workflow_step": _workflow_step,
    "workflow_run": _workflow_run,
    "model_routing": _model_routing,
    "steer_queued": _steer,
    "steer_consumed": _steer,
    "artifact": _artifact,
    "artifact_rejected": _artifact_rejected,
}


def project_chat_event(event: dict[str, Any]) -> dict[str, Any]:
    """Return exactly one reviewed public frame or a fixed redacted notice.

    Unknown runtime types, malformed frames and all unreviewed keys collapse to
    one content-free marker.  In particular, an internal type name is not
    reflected back to the browser.
    """

    event_type = event.get("type")
    projector = _PROJECTORS.get(event_type) if isinstance(event_type, str) else None
    if projector is None:
        return {"type": "event_unavailable", "reason": "unsupported_event"}
    try:
        return projector(event)
    except _UnsupportedEvent:
        return {"type": "event_unavailable", "reason": "malformed_event"}


__all__ = ["project_chat_event"]
