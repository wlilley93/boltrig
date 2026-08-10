"""Closed authored fields inside otherwise lossless workflow definitions."""

from __future__ import annotations

from typing import Any

from boltrig.models.libraries import (
    WORKFLOW_LOOP_BINDING_KEY_PATTERN,
    WORKFLOW_LOOP_BINDING_SOURCES,
    WORKFLOW_LOOP_MAX_BINDINGS,
)

_OBJECT: dict[str, Any] = {"type": "object"}
_STRING: dict[str, Any] = {"type": "string"}
_STRINGS: dict[str, Any] = {"type": "array", "items": _STRING}
_LOOP_BINDINGS: dict[str, Any] = {
    "type": "object",
    "maxProperties": WORKFLOW_LOOP_MAX_BINDINGS,
    "propertyNames": {
        "type": "string",
        "pattern": WORKFLOW_LOOP_BINDING_KEY_PATTERN,
    },
    "additionalProperties": {
        "type": "string",
        "enum": list(WORKFLOW_LOOP_BINDING_SOURCES),
    },
}
_RETRY: dict[str, Any] = {
    # Per-step retry, clamped again at runtime (interpreter policy bounds).
    "type": "object",
    "properties": {
        "max": {"type": "integer", "minimum": 0, "maximum": 5},
        "interval_ms": {"type": "integer", "minimum": 0, "maximum": 60_000},
    },
    "additionalProperties": False,
}
_STEP: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": _STRING,
        "action": _STRING,
        "parents": _STRINGS,
        "description": _STRING,
        "params": _OBJECT,
        "with": _OBJECT,
        "branch": _STRING,
        "loop_bindings": _LOOP_BINDINGS,
        # Error handling (graphon-parity): how an exhausted step failure
        # resolves - poison descendants (fail), route success/fail arms
        # (branch), or substitute a declared default output (default).
        "on_error": {"type": "string", "enum": ["fail", "branch", "default"]},
        "default_output": _OBJECT,
        "retry": _RETRY,
    },
    "required": ["id", "action"],
    "additionalProperties": True,
}
WORKFLOW_DEFINITION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "steps": {"type": "array", "items": _STEP},
    },
    "additionalProperties": True,
}
