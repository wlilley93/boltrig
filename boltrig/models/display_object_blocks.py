"""Shape validation for reviewed chat display-object primitives."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

_BLOCK_TYPES = frozenset(
    {"text", "markdown", "code", "notice", "divider", "key_value", "metrics", "table",
     "progress", "steps", "timeline", "chart", "image", "gallery", "diff", "source", "map"}
)


def validate_display_block(value: Any, error: Callable[[str], Exception]) -> dict[str, Any]:
    """Validate the fields a renderer will dereference before returning a copy."""
    if not isinstance(value, dict) or value.get("type") not in _BLOCK_TYPES:
        raise error("display block type is unsupported")
    if not _block_shape(value):
        raise error("display block shape is invalid")
    return dict(value)


def _block_shape(value: dict[str, Any]) -> bool:
    block_type = value["type"]
    if block_type in {"text", "markdown"}:
        return _text(value.get("text"), 32_768)
    if block_type == "code":
        return _text(value.get("code"), 32_768) and _optional_text(value.get("language"), 80)
    if block_type == "notice":
        return _text(value.get("text"), 4_000) and _choice(
            value.get("tone"), {"neutral", "info", "warning", "danger", "success"}
        )
    if block_type == "divider":
        return True
    if block_type == "key_value":
        return _objects(value.get("items"), 40, _key_value)
    if block_type == "metrics":
        return _objects(value.get("items"), 24, _metric)
    if block_type == "table":
        return _table(value)
    if block_type == "progress":
        return _finite(value.get("value")) and _positive(value.get("max")) \
            and _optional_text(value.get("label"), 200)
    if block_type == "steps":
        return _objects(value.get("items"), 50, _step)
    if block_type == "timeline":
        return _objects(value.get("items"), 50, _timeline)
    if block_type == "chart":
        return _choice(value.get("chart"), {"bar", "line", "donut"}) \
            and _objects(value.get("series"), 50, _series)
    if block_type == "image":
        return _image(value)
    if block_type == "gallery":
        return _objects(value.get("items"), 24, _image)
    if block_type == "diff":
        return _text(value.get("before"), 32_768, empty=True) \
            and _text(value.get("after"), 32_768, empty=True) \
            and _optional_text(value.get("label"), 200)
    if block_type == "source":
        return _text(value.get("label"), 500) and _optional_text(value.get("url"), 2_048)
    return _map(value)


def _key_value(value: dict[str, Any]) -> bool:
    return _text(value.get("label"), 200) and _text(value.get("value"), 4_000)


def _metric(value: dict[str, Any]) -> bool:
    return _text(value.get("label"), 200) and _text(value.get("value"), 1_000) \
        and _optional_text(value.get("change"), 200)


def _step(value: dict[str, Any]) -> bool:
    return _text(value.get("label"), 500) and _optional_text(value.get("status"), 80)


def _timeline(value: dict[str, Any]) -> bool:
    return _text(value.get("label"), 500) \
        and _optional_text(value.get("detail"), 4_000) \
        and _optional_text(value.get("time"), 120) \
        and _optional_text(value.get("status"), 80)


def _series(value: dict[str, Any]) -> bool:
    return _text(value.get("label"), 200) and _finite(value.get("value")) \
        and _optional_text(value.get("color"), 80)


def _image(value: dict[str, Any]) -> bool:
    return _text(value.get("url"), 2_048) and _text(value.get("alt"), 500) \
        and _optional_text(value.get("caption"), 1_000)


def _map(value: dict[str, Any]) -> bool:
    return _coordinate(value.get("latitude"), -90, 90) \
        and _coordinate(value.get("longitude"), -180, 180) \
        and _text(value.get("label"), 500) and _integer(value.get("zoom"), 0, 22)


def _table(value: dict[str, Any]) -> bool:
    columns = value.get("columns")
    rows = value.get("rows")
    if not isinstance(columns, list) or not 0 < len(columns) <= 12:
        return False
    if not all(_text(column, 200) for column in columns):
        return False
    return isinstance(rows, list) and len(rows) <= 100 and all(
        isinstance(row, list) and len(row) <= len(columns)
        and all(_text(cell, 4_000, empty=True) for cell in row) for row in rows
    )


def _objects(value: Any, maximum: int, validator: Callable[[dict[str, Any]], bool]) -> bool:
    return isinstance(value, list) and len(value) <= maximum and all(
        isinstance(item, dict) and validator(item) for item in value
    )


def _text(value: Any, maximum: int, *, empty: bool = False) -> bool:
    return isinstance(value, str) and (empty or bool(value)) and len(value) <= maximum


def _optional_text(value: Any, maximum: int) -> bool:
    return value is None or _text(value, maximum, empty=True)


def _choice(value: Any, choices: set[str]) -> bool:
    return value is None or value in choices


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _positive(value: Any) -> bool:
    return value is None or (_finite(value) and value > 0)


def _coordinate(value: Any, minimum: float, maximum: float) -> bool:
    return _finite(value) and minimum <= value <= maximum


def _integer(value: Any, minimum: int, maximum: int) -> bool:
    return value is None or (
        isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum
    )


__all__ = ["validate_display_block"]
