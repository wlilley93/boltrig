"""Closed JSON contract for safe, model-authored chat display objects."""

from __future__ import annotations

import json
import math
import re
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from boltrig.models.display_object_blocks import validate_display_block

DISPLAY_OBJECT_SCHEMA = "boltrig.display.v1"
DISPLAY_OBJECT_KINDS = frozenset(
    {
        "content.markdown", "content.code", "content.image", "content.file",
        "content.sources", "content.gallery", "artifact.card",
        "status.notice", "status.progress", "status.steps", "status.system",
        "status.feedback", "status.tool_receipt", "status.coordination",
        "status.execution_target", "status.screen_context", "status.computer_batch",
        "question.text", "question.single_select", "question.multi_select",
        "question.date", "question.datetime", "question.person", "question.agent",
        "question.connection", "question.recipient", "question.file", "question.form",
        "question.rank", "confirmation.simple", "confirmation.destructive",
        "confirmation.typed", "approval.action", "data.table", "data.key_value",
        "data.metrics", "data.chart", "data.timeline", "data.map", "data.place",
        "data.diff", "email.draft", "email.sent", "slack.message.draft",
        "slack.message.sent", "teams.message.draft", "teams.message.sent",
        "whatsapp.message.draft", "whatsapp.message.sent", "telegram.message.draft",
        "telegram.message.sent", "webhook.request.draft", "webhook.request.sent",
        "ticket.issue", "ticket.draft", "calendar.event", "calendar.event.draft",
        "contact.card", "document.card", "opbox.entity", "opbox.action", "task.card",
        "routine.card", "custom.card",
    }
)

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_ACTIONS = frozenset(
    {
        "edit", "change_recipient", "send", "discard", "reply", "submit",
        "confirm", "cancel", "approve", "reject", "retry", "open", "download", "copy",
    }
)
_STATUSES = frozenset(
    {"draft", "ready", "pending", "sending", "sent", "done", "failed", "cancelled",
     "informational"}
)
_FIELD_TYPES = frozenset(
    {"text", "textarea", "number", "date", "datetime", "select", "multi_select",
     "person", "agent", "connection", "recipient", "checkbox", "file"}
)
_BLOCK_TYPES = frozenset(
    {"text", "markdown", "code", "notice", "divider", "key_value", "metrics", "table",
     "progress", "steps", "timeline", "chart", "image", "gallery", "diff", "source", "map"}
)
_MAX_BYTES = 65_536
_ENVELOPE_KEYS = frozenset(
    {"schema", "id", "kind", "title", "subtitle", "status", "revision", "data", "fields",
     "blocks", "actions", "provenance"}
)


class DisplayObjectValidationError(ValueError):
    """An object is outside the reviewed browser contract."""


def build_display_object(
    value: dict[str, Any], *, run_id: str, agent_address: str
) -> dict[str, Any]:
    """Stamp trusted identity and apply safe template defaults."""
    candidate = dict(value)
    candidate.setdefault("schema", DISPLAY_OBJECT_SCHEMA)
    candidate.setdefault("id", f"do_{uuid.uuid4().hex}")
    kind = candidate.get("kind")
    candidate.setdefault("status", _default_status(kind))
    candidate.setdefault("revision", 1)
    candidate.setdefault("actions", _default_actions(kind, candidate.get("data")))
    # Provenance is authority-bearing metadata.  A model may describe sources
    # in ordinary card data, but it cannot mint provider or connection truth.
    # Provider receipts can still enter through the trusted projection path and
    # are validated by ``validate_display_object`` directly.
    candidate["provenance"] = {
        "run_id": run_id,
        "agent_address": agent_address,
    }
    return validate_display_object(candidate)


def validate_display_object(value: Any) -> dict[str, Any]:
    """Return an exact bounded copy or raise without reflecting secret values."""
    if not isinstance(value, dict) or set(value) - _ENVELOPE_KEYS:
        raise DisplayObjectValidationError("display object envelope is malformed")
    if value.get("schema") != DISPLAY_OBJECT_SCHEMA:
        raise DisplayObjectValidationError("display object schema is unsupported")
    object_id = _required_text(value, "id", 128)
    if _ID.fullmatch(object_id) is None:
        raise DisplayObjectValidationError("display object id is invalid")
    kind = _required_text(value, "kind", 80)
    if kind not in DISPLAY_OBJECT_KINDS:
        raise DisplayObjectValidationError("display object kind is unsupported")
    title = _required_text(value, "title", 200)
    data = value.get("data")
    if not isinstance(data, dict):
        raise DisplayObjectValidationError("display object data is invalid")
    _safe_json(data)
    _kind_shape(kind, data)
    out: dict[str, Any] = {
        "schema": DISPLAY_OBJECT_SCHEMA, "id": object_id, "kind": kind,
        "title": title, "data": data,
    }
    _optional_text_into(value, out, "subtitle", 400)
    _enum_into(value, out, "status", _STATUSES)
    _integer_into(value, out, "revision", 1, 1_000_000)
    _list_into(value, out, "actions", 8, _action)
    _list_into(value, out, "fields", 24, _field)
    _list_into(value, out, "blocks", 32, _block)
    if "provenance" in value:
        out["provenance"] = _provenance(value["provenance"])
    try:
        encoded = json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode()
    except (TypeError, ValueError) as exc:
        raise DisplayObjectValidationError("display object is not JSON") from exc
    if len(encoded) > _MAX_BYTES:
        raise DisplayObjectValidationError("display object is too large")
    return out


def _default_status(kind: Any) -> str:
    if isinstance(kind, str) and kind.endswith(".draft"):
        return "draft"
    if isinstance(kind, str) and kind.endswith(".sent"):
        return "sent"
    return "informational"


def _default_actions(kind: Any, data: Any) -> list[dict[str, Any]]:
    if kind == "email.draft" or (isinstance(kind, str) and kind.endswith(".message.draft")):
        actions = [
            _action_row("edit", "Edit", "secondary"),
            _action_row("change-recipient", "Change recipient", "secondary", "change_recipient"),
        ]
        can_send = kind == "email.draft" or (
            isinstance(data, dict)
            and any(isinstance(data.get(key), str) for key in ("channel_id", "connection_id"))
        )
        if can_send:
            actions.append(_action_row("send", "Send", "primary", confirm=True))
        actions.append(_action_row("discard", "Discard", "secondary"))
        return actions
    if isinstance(kind, str) and kind.startswith("question."):
        return [_action_row("submit", "Reply", "primary"), _action_row("cancel", "Cancel", "secondary")]
    if isinstance(kind, str) and (kind.startswith("confirmation.") or kind == "approval.action"):
        return [_action_row("confirm", "Confirm", "primary"), _action_row("cancel", "Cancel", "secondary")]
    return []


def _action_row(
    action_id: str, label: str, style: str, intent: str | None = None, confirm: bool = False
) -> dict[str, Any]:
    return {
        "id": action_id, "label": label, "intent": intent or action_id.replace("-", "_"),
        "style": style, **({"requires_confirmation": True} if confirm else {}),
    }


def _action(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - {
        "id", "label", "intent", "style", "requires_confirmation"
    }:
        raise DisplayObjectValidationError("display action is malformed")
    action_id = _required_text(value, "id", 64)
    if _ID.fullmatch(action_id) is None:
        raise DisplayObjectValidationError("display action id is invalid")
    out: dict[str, Any] = {
        "id": action_id, "label": _required_text(value, "label", 100),
        "intent": _required_text(value, "intent", 64),
    }
    if out["intent"] not in _ACTIONS:
        raise DisplayObjectValidationError("display action intent is unsupported")
    _enum_into(value, out, "style", frozenset({"primary", "secondary", "danger"}))
    if "requires_confirmation" in value:
        if not isinstance(value["requires_confirmation"], bool):
            raise DisplayObjectValidationError("display action confirmation flag is invalid")
        out["requires_confirmation"] = value["requires_confirmation"]
    return out


def _field(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - {
        "id", "label", "type", "value", "options", "placeholder", "required", "help"
    }:
        raise DisplayObjectValidationError("display field is malformed")
    out: dict[str, Any] = {
        "id": _required_text(value, "id", 64), "label": _required_text(value, "label", 120),
        "type": _required_text(value, "type", 40),
    }
    if _ID.fullmatch(out["id"]) is None or out["type"] not in _FIELD_TYPES:
        raise DisplayObjectValidationError("display field type is unsupported")
    if "value" in value:
        _field_value(value["value"])
        out["value"] = value["value"]
    _list_into(value, out, "options", 50, _field_option)
    _optional_text_into(value, out, "placeholder", 200)
    _optional_text_into(value, out, "help", 300)
    if "required" in value:
        if not isinstance(value["required"], bool):
            raise DisplayObjectValidationError("display field required flag is invalid")
        out["required"] = value["required"]
    return out


def _field_option(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"label", "value"}:
        raise DisplayObjectValidationError("display field option is malformed")
    return {"label": _required_text(value, "label", 120), "value": _required_text(value, "value", 200)}


def _block(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("type") not in _BLOCK_TYPES:
        raise DisplayObjectValidationError("display block type is unsupported")
    _safe_json(value)
    return validate_display_block(value, DisplayObjectValidationError)


def _provenance(value: Any) -> dict[str, str]:
    keys = {"run_id": 128, "agent_address": 128, "provider": 80,
            "connection_label": 160, "source_label": 240}
    if not isinstance(value, dict) or set(value) - set(keys):
        raise DisplayObjectValidationError("display provenance is malformed")
    out: dict[str, str] = {}
    for key, max_length in keys.items():
        _optional_text_into(value, out, key, max_length)
    return out


def _kind_shape(kind: str, data: dict[str, Any]) -> None:
    if kind == "email.draft":
        _string_list(data.get("to"), "email recipients")
        _required_value_text(data, "body", 32_768)
        _optional_value_text(data, "subject", 500)
    elif kind.endswith(".message.draft"):
        body = data.get("body", data.get("text"))
        if not isinstance(body, str) or not body.strip() or len(body) > 32_768:
            raise DisplayObjectValidationError("message draft body is invalid")
    elif kind.startswith("question."):
        _one_text(data, ("prompt", "summary"), 4_000)
    elif kind.startswith("confirmation.") or kind == "approval.action":
        _one_text(data, ("summary", "message"), 4_000)
        if kind == "confirmation.typed":
            _required_value_text(data, "phrase", 200)
    elif kind in {"data.map", "data.place"}:
        _coordinate(data.get("latitude"), -90, 90)
        _coordinate(data.get("longitude"), -180, 180)


def _safe_json(value: Any, depth: int = 0) -> None:
    if value is None or isinstance(value, (bool, str)):
        if isinstance(value, str) and len(value) > 32_768:
            raise DisplayObjectValidationError("display text is too long")
        return
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            raise DisplayObjectValidationError("display number is invalid")
        return
    if depth >= 6:
        raise DisplayObjectValidationError("display data is too deeply nested")
    if isinstance(value, list):
        if len(value) > 100:
            raise DisplayObjectValidationError("display list is too long")
        for item in value:
            _safe_json(item, depth + 1)
        return
    if not isinstance(value, dict) or len(value) > 64:
        raise DisplayObjectValidationError("display data is malformed")
    for key, item in value.items():
        if not isinstance(key, str) or len(key) > 80:
            raise DisplayObjectValidationError("display data key is invalid")
        _safe_url_or_coordinate(key, item)
        _safe_json(item, depth + 1)


def _safe_url_or_coordinate(key: str, value: Any) -> None:
    lowered = key.lower()
    if lowered in {"url", "href", "image_url"} and isinstance(value, str):
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise DisplayObjectValidationError("display URL is not allowed")
    if lowered in {"lat", "latitude"}:
        _coordinate(value, -90, 90)
    if lowered in {"lng", "lon", "longitude"}:
        _coordinate(value, -180, 180)


def _required_text(value: dict[str, Any], key: str, maximum: int) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item or len(item) > maximum:
        raise DisplayObjectValidationError(f"display {key} is invalid")
    return item


def _optional_text_into(source: dict[str, Any], target: dict[str, Any], key: str, maximum: int) -> None:
    if key not in source:
        return
    target[key] = _required_text(source, key, maximum)


def _enum_into(source: dict[str, Any], target: dict[str, Any], key: str, choices: frozenset[str]) -> None:
    if key not in source:
        return
    item = _required_text(source, key, 64)
    if item not in choices:
        raise DisplayObjectValidationError(f"display {key} is unsupported")
    target[key] = item


def _integer_into(
    source: dict[str, Any], target: dict[str, Any], key: str, minimum: int, maximum: int
) -> None:
    if key not in source:
        return
    item = source[key]
    if not isinstance(item, int) or isinstance(item, bool) or not minimum <= item <= maximum:
        raise DisplayObjectValidationError(f"display {key} is invalid")
    target[key] = item


def _list_into(
    source: dict[str, Any], target: dict[str, Any], key: str, maximum: int,
    parser: Callable[[Any], Any],
) -> None:
    if key not in source:
        return
    items = source[key]
    if not isinstance(items, list) or len(items) > maximum:
        raise DisplayObjectValidationError(f"display {key} is invalid")
    target[key] = [parser(item) for item in items]


def _field_value(value: Any) -> None:
    if isinstance(value, bool) or (isinstance(value, (int, float)) and math.isfinite(value)):
        return
    if isinstance(value, str) and len(value) <= 4_000:
        return
    if isinstance(value, list) and len(value) <= 50 and all(
        isinstance(item, str) and len(item) <= 200 for item in value
    ):
        return
    raise DisplayObjectValidationError("display field value is invalid")


def _coordinate(value: Any, minimum: float, maximum: float) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise DisplayObjectValidationError("display coordinate is invalid")
    if not minimum <= value <= maximum:
        raise DisplayObjectValidationError("display coordinate is out of bounds")


def _string_list(value: Any, label: str) -> None:
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list) or not 1 <= len(items) <= 50 or not all(
        isinstance(item, str) and 0 < len(item) <= 320 for item in items
    ):
        raise DisplayObjectValidationError(f"{label} are invalid")


def _required_value_text(data: dict[str, Any], key: str, maximum: int) -> None:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise DisplayObjectValidationError(f"display data {key} is invalid")


def _optional_value_text(data: dict[str, Any], key: str, maximum: int) -> None:
    if key in data and (not isinstance(data[key], str) or len(data[key]) > maximum):
        raise DisplayObjectValidationError(f"display data {key} is invalid")


def _one_text(data: dict[str, Any], keys: tuple[str, ...], maximum: int) -> None:
    if not any(isinstance(data.get(key), str) and 0 < len(data[key]) <= maximum for key in keys):
        raise DisplayObjectValidationError("display summary is invalid")


__all__ = [
    "DISPLAY_OBJECT_KINDS", "DISPLAY_OBJECT_SCHEMA", "DisplayObjectValidationError",
    "build_display_object", "validate_display_object",
]
