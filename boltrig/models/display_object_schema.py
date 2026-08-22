"""Agent-facing JSON Schema for the closed chat display-object vocabulary."""

from __future__ import annotations

from typing import Any


def display_object_input_schema(kinds: frozenset[str]) -> dict[str, Any]:
    """Describe every composable primitive without accepting model-authored code."""
    return {
        "type": "object",
        "properties": {
            "id": _string(128, description="Stable object id when revising an earlier card."),
            "kind": {
                "type": "string", "enum": sorted(kinds),
                "description": "Reviewed semantic template. Use custom.card for novel compositions.",
            },
            "title": _string(200, minimum=1),
            "subtitle": _string(400),
            "status": {
                "type": "string", "enum": [
                    "draft", "ready", "pending", "sending", "sent", "done",
                    "failed", "cancelled", "informational",
                ],
            },
            "revision": {"type": "integer", "minimum": 1, "maximum": 1_000_000},
            "data": {
                "type": "object", "maxProperties": 64,
                "description": _DATA_HELP,
            },
            "fields": {"type": "array", "maxItems": 24, "items": _field_schema()},
            "blocks": {"type": "array", "maxItems": 32, "items": {"oneOf": _block_schemas()}},
            "actions": {"type": "array", "maxItems": 8, "items": _action_schema()},
        },
        "required": ["kind", "title", "data"],
        "additionalProperties": False,
    }


_DATA_HELP = (
    "Bounded semantic values. Common shapes: email.draft={to:string[], cc?:string[], "
    "subject?:string, body:string}; Slack/Teams/WhatsApp/Telegram draft={channel_id or "
    "connection_id:string, "
    "workspace_label?:string, recipient:string, thread_label?:string, body:string}; "
    "question.*={prompt:string, options?:string[]}; confirmation.*={summary:string, "
    "phrase?:string}; data.map={latitude:number, longitude:number, label:string}. "
    "Novel visuals belong in custom.card blocks. Never provide HTML, JSX, CSS or JavaScript."
)


def _field_schema() -> dict[str, Any]:
    return {
        "type": "object", "additionalProperties": False,
        "properties": {
            "id": _string(64, minimum=1), "label": _string(120, minimum=1),
            "type": {
                "type": "string", "enum": [
                    "text", "textarea", "number", "date", "datetime", "select",
                    "multi_select", "person", "agent", "connection", "recipient",
                    "checkbox", "file",
                ],
            },
            "value": {}, "options": {"type": "array", "maxItems": 50, "items": {
                "type": "object", "additionalProperties": False,
                "properties": {"label": _string(120, minimum=1), "value": _string(200, minimum=1)},
                "required": ["label", "value"],
            }},
            "placeholder": _string(200), "required": {"type": "boolean"},
            "help": _string(300),
        },
        "required": ["id", "label", "type"],
    }


def _action_schema() -> dict[str, Any]:
    return {
        "type": "object", "additionalProperties": False,
        "properties": {
            "id": _string(64, minimum=1), "label": _string(100, minimum=1),
            "intent": {
                "type": "string", "enum": [
                    "edit", "change_recipient", "send", "discard", "reply", "submit",
                    "confirm", "cancel", "approve", "reject", "retry", "open", "download", "copy",
                ],
            },
            "style": {"type": "string", "enum": ["primary", "secondary", "danger"]},
            "requires_confirmation": {"type": "boolean"},
        },
        "required": ["id", "label", "intent"],
    }


def _block_schemas() -> list[dict[str, Any]]:
    return [
        _block(["text", "markdown"], {"text": _string(32_768, minimum=1)}, ["text"]),
        _block(["code"], {"code": _string(32_768, minimum=1), "language": _string(80)}, ["code"]),
        _block(["notice"], {
            "text": _string(4_000, minimum=1),
            "tone": {"type": "string", "enum": ["neutral", "info", "warning", "danger", "success"]},
        }, ["text"]),
        _block(["divider"], {}, []),
        _items_block("key_value", _label_value(200, 4_000), 40),
        _items_block("metrics", _metric_item(), 24),
        _table_block(),
        _block(["progress"], {
            "value": {"type": "number"}, "max": {"type": "number", "exclusiveMinimum": 0},
            "label": _string(200),
        }, ["value"]),
        _items_block("steps", _step_item(), 50),
        _items_block("timeline", _timeline_item(), 50),
        _items_block("chart", _series_item(), 50, extra={
            "chart": {"type": "string", "enum": ["bar", "line", "donut"]},
        }, item_key="series"),
        _image_block(), _gallery_block(),
        _block(["diff"], {
            "before": _string(32_768), "after": _string(32_768), "label": _string(200),
        }, ["before", "after"]),
        _block(["source"], {"label": _string(500, minimum=1), "url": _https_url()}, ["label"]),
        _block(["map"], {
            "latitude": {"type": "number", "minimum": -90, "maximum": 90},
            "longitude": {"type": "number", "minimum": -180, "maximum": 180},
            "label": _string(500, minimum=1),
            "zoom": {"type": "integer", "minimum": 0, "maximum": 22},
        }, ["latitude", "longitude", "label"]),
    ]


def _block(types: list[str], properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object", "additionalProperties": False,
        "properties": {"type": {"type": "string", "enum": types}, **properties},
        "required": ["type", *required],
    }


def _items_block(
    kind: str, item: dict[str, Any], maximum: int, *,
    extra: dict[str, Any] | None = None, item_key: str = "items",
) -> dict[str, Any]:
    return _block([kind], {
        **(extra or {}), item_key: {"type": "array", "maxItems": maximum, "items": item},
    }, [item_key])


def _label_value(label_max: int, value_max: int) -> dict[str, Any]:
    return _object({
        "label": _string(label_max, minimum=1), "value": _string(value_max, minimum=1),
    }, ["label", "value"])


def _metric_item() -> dict[str, Any]:
    return _object({
        "label": _string(200, minimum=1), "value": _string(1_000, minimum=1),
        "change": _string(200),
    }, ["label", "value"])


def _step_item() -> dict[str, Any]:
    return _object({"label": _string(500, minimum=1), "status": _string(80)}, ["label"])


def _timeline_item() -> dict[str, Any]:
    return _object({
        "label": _string(500, minimum=1), "detail": _string(4_000),
        "time": _string(120), "status": _string(80),
    }, ["label"])


def _series_item() -> dict[str, Any]:
    return _object({
        "label": _string(200, minimum=1), "value": {"type": "number"}, "color": _string(80),
    }, ["label", "value"])


def _table_block() -> dict[str, Any]:
    return _block(["table"], {
        "columns": {"type": "array", "minItems": 1, "maxItems": 12, "items": _string(200, minimum=1)},
        "rows": {"type": "array", "maxItems": 100, "items": {
            "type": "array", "maxItems": 12, "items": _string(4_000),
        }},
    }, ["columns", "rows"])


def _image_properties() -> dict[str, Any]:
    return {"url": _https_url(), "alt": _string(500, minimum=1), "caption": _string(1_000)}


def _image_block() -> dict[str, Any]:
    return _block(["image"], _image_properties(), ["url", "alt"])


def _gallery_block() -> dict[str, Any]:
    return _items_block("gallery", _object(_image_properties(), ["url", "alt"]), 24)


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object", "additionalProperties": False,
        "properties": properties, "required": required,
    }


def _https_url() -> dict[str, Any]:
    return {"type": "string", "format": "uri", "pattern": "^https://", "maxLength": 2_048}


def _string(maximum: int, *, minimum: int = 0, description: str | None = None) -> dict[str, Any]:
    return {
        "type": "string", "minLength": minimum, "maxLength": maximum,
        **({"description": description} if description else {}),
    }


__all__ = ["display_object_input_schema"]
