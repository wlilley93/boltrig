"""Schemas and bounded constants for the visual browser adapter."""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import VerbSpec
from boltrig.adapters.builtin.script_base import schema

DEFAULT_TIMEOUT = 60.0
DEFAULT_HOME = "/var/lib/boltrig/browser-cli"
MAX_FRAME_BYTES = 2 * 1024 * 1024
MAX_FRAME_DIMENSION = 1600
MAX_FRAMES = 24
MAX_FRAMES_PER_SCOPE = 4
MAX_TEXT_BYTES = 8_000
MAX_COORDINATE = 16_384
MAX_AX_NODES = 80

NAME = {
    "type": "string",
    "minLength": 1,
    "maxLength": 64,
    "pattern": "^[A-Za-z0-9_-]+$",
}
FRAME_ID = {
    "type": "string",
    "minLength": 1,
    "maxLength": 64,
    "pattern": "^[A-Za-z0-9_-]+$",
}
TARGET_ID = {
    "type": "string",
    "minLength": 1,
    "maxLength": 256,
    "pattern": "^[A-Za-z0-9_-]+$",
}
FRAME_VIEW: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": FRAME_ID,
        "media_type": {"const": "image/jpeg"},
        "width": {"type": "integer", "minimum": 1, "maximum": MAX_COORDINATE},
        "height": {"type": "integer", "minimum": 1, "maximum": MAX_COORDINATE},
        "url": {"type": "string", "maxLength": 4096},
        "title": {"type": "string", "maxLength": 512},
        "captured_at": {"type": "string", "maxLength": 64},
    },
    "required": ["id", "media_type", "width", "height", "url", "title", "captured_at"],
    "additionalProperties": False,
}
ACTION_OUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["ok", "stale_frame"]},
        "frame": FRAME_VIEW,
        "cursor": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "minimum": 0, "maximum": MAX_COORDINATE},
                "y": {"type": "integer", "minimum": 0, "maximum": MAX_COORDINATE},
                "kind": {"type": "string", "enum": ["click", "type", "scroll", "key"]},
            },
            "required": ["x", "y", "kind"],
            "additionalProperties": False,
        },
    },
    "required": ["status", "frame"],
    "additionalProperties": False,
}


def browser_verb_specs() -> list[VerbSpec]:
    return [*_basic_verbs(), *_navigation_verbs(), *_interaction_verbs(), *_frame_verbs()]


def _basic_verbs() -> list[VerbSpec]:
    any_out = {"type": "object"}
    page_out = {
        "type": "object",
        "properties": {
            "command": {"type": "array", "items": {"type": "string"}},
            "result": {"type": "object"},
        },
        "required": ["command", "result"],
        "additionalProperties": False,
    }
    return [
        VerbSpec(
            "browser.doctor", "browser", schema(), any_out, "low", "Run Browser Use diagnostics."
        ),
        VerbSpec(
            "browser.auth.status",
            "browser",
            schema(),
            any_out,
            "low",
            "Read Browser Use auth status.",
        ),
        VerbSpec(
            "browser.page.info",
            "browser",
            schema(props={"name": NAME}),
            page_out,
            "low",
            "Read information about the active browser page.",
        ),
        VerbSpec(
            "browser.tab.open",
            "browser",
            schema(["url"], {"url": {"type": "string", "maxLength": 4096}, "name": NAME}),
            page_out,
            "high",
            "Open a public HTTP(S) URL in a browser tab.",
        ),
        VerbSpec(
            "browser.remote.start",
            "browser",
            schema(["name"], {"name": NAME}),
            any_out,
            "high",
            "Start a named Browser Use remote daemon.",
        ),
        VerbSpec(
            "browser.remote.stop",
            "browser",
            schema(["name"], {"name": NAME}),
            any_out,
            "high",
            "Stop a named Browser Use remote daemon.",
        ),
    ]


def _navigation_verbs() -> list[VerbSpec]:
    low_read = {"per": "minute", "max": 60, "scope": "tenant"}
    bounded_action = {"per": "minute", "max": 120, "scope": "tenant"}
    tabs_out = {
        "type": "object",
        "properties": {
            "tabs": {
                "type": "array",
                "maxItems": 100,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": TARGET_ID,
                        "title": {"type": "string", "maxLength": 512},
                        "url": {"type": "string", "maxLength": 4096},
                    },
                    "required": ["id", "title", "url"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["tabs"],
        "additionalProperties": False,
    }
    return [
        VerbSpec(
            "browser.navigate",
            "browser",
            schema(["url"], {"url": {"type": "string", "maxLength": 4096}, "name": NAME}),
            ACTION_OUT,
            "high",
            "Navigate the active tab to a public HTTP(S) URL.",
            rate_limit=bounded_action,
            idempotency_mode="disabled",
        ),
        VerbSpec(
            "browser.tabs.list",
            "browser",
            schema(props={"name": NAME}),
            tabs_out,
            "low",
            "List open browser tabs without exposing browser internals.",
            rate_limit=low_read,
        ),
        *_tab_mutation_verbs(bounded_action),
        VerbSpec(
            "browser.snapshot",
            "browser",
            schema(props={"name": NAME}),
            ACTION_OUT,
            "low",
            "Capture one bounded ephemeral browser frame.",
            rate_limit=low_read,
            idempotency_mode="disabled",
        ),
    ]


def _tab_mutation_verbs(rate_limit: dict[str, Any]) -> list[VerbSpec]:
    return [
        VerbSpec(
            "browser.tab.select",
            "browser",
            schema(["target_id"], {"target_id": TARGET_ID, "name": NAME}),
            ACTION_OUT,
            "low",
            "Select an existing browser tab and capture it.",
            rate_limit=rate_limit,
            idempotency_mode="disabled",
        ),
        VerbSpec(
            "browser.tab.close",
            "browser",
            schema(["target_id"], {"target_id": TARGET_ID, "name": NAME}),
            ACTION_OUT,
            "high",
            "Close an existing browser tab and capture the remaining tab.",
            rate_limit=rate_limit,
            idempotency_mode="disabled",
        ),
    ]


def _interaction_verbs() -> list[VerbSpec]:
    coordinate = {"type": "integer", "minimum": 0, "maximum": MAX_COORDINATE}
    action = {"expected_frame_id": FRAME_ID, "name": NAME}
    rate = {"per": "minute", "max": 120, "scope": "tenant"}
    return [
        VerbSpec(
            "browser.click",
            "browser",
            schema(
                ["expected_frame_id", "x", "y"],
                {
                    **action,
                    "x": coordinate,
                    "y": coordinate,
                    "button": {"type": "string", "enum": ["left", "right", "middle"]},
                },
            ),
            ACTION_OUT,
            "high",
            "Click an exact point on the currently displayed frame.",
            rate_limit=rate,
            idempotency_mode="disabled",
        ),
        VerbSpec(
            "browser.type",
            "browser",
            schema(
                ["expected_frame_id", "text"],
                {**action, "text": {"type": "string", "maxLength": MAX_TEXT_BYTES}},
            ),
            ACTION_OUT,
            "high",
            "Type bounded text into the focused browser control.",
            rate_limit=rate,
            idempotency_mode="disabled",
        ),
        *_scroll_and_key_verbs(action, coordinate, rate),
    ]


def _scroll_and_key_verbs(
    action: dict[str, Any], coordinate: dict[str, Any], rate: dict[str, Any]
) -> list[VerbSpec]:
    keys = [
        "Enter",
        "Tab",
        "Escape",
        "Backspace",
        "Delete",
        "ArrowLeft",
        "ArrowRight",
        "ArrowUp",
        "ArrowDown",
        "Home",
        "End",
        "PageUp",
        "PageDown",
    ]
    return [
        VerbSpec(
            "browser.scroll",
            "browser",
            schema(
                ["expected_frame_id", "x", "y", "delta_x", "delta_y"],
                {
                    **action,
                    "x": coordinate,
                    "y": coordinate,
                    "delta_x": {"type": "integer", "minimum": -10_000, "maximum": 10_000},
                    "delta_y": {"type": "integer", "minimum": -10_000, "maximum": 10_000},
                },
            ),
            ACTION_OUT,
            "low",
            "Scroll from an exact point on the currently displayed frame.",
            rate_limit=rate,
            idempotency_mode="disabled",
        ),
        VerbSpec(
            "browser.key.press",
            "browser",
            schema(
                ["expected_frame_id", "key"],
                {**action, "key": {"type": "string", "enum": keys}},
            ),
            ACTION_OUT,
            "high",
            "Press one allow-listed browser key.",
            rate_limit=rate,
            idempotency_mode="disabled",
        ),
    ]


def _frame_verbs() -> list[VerbSpec]:
    low_read = {"per": "minute", "max": 60, "scope": "tenant"}
    frame_data = {
        "type": "object",
        "properties": {
            "id": FRAME_ID,
            "media_type": {"const": "image/jpeg"},
            "data": {
                "type": "string",
                "maxLength": ((MAX_FRAME_BYTES + 2) // 3) * 4,
                "pattern": "^[A-Za-z0-9+/]*={0,2}$",
            },
        },
        "required": ["id", "media_type", "data"],
        "additionalProperties": False,
    }
    return [
        _inspect_verb(low_read),
        VerbSpec(
            "browser.frames.list",
            "browser",
            schema(
                ["limit"],
                {"limit": {"type": "integer", "minimum": 1, "maximum": 100}, "name": NAME},
            ),
            {
                "type": "object",
                "properties": {"frames": {"type": "array", "maxItems": 100, "items": FRAME_VIEW}},
                "required": ["frames"],
                "additionalProperties": False,
            },
            "low",
            "List the caller's bounded ephemeral browser frames.",
            rate_limit=low_read,
            idempotency_mode="disabled",
        ),
        VerbSpec(
            "browser.frame.read",
            "browser",
            schema(["id"], {"id": FRAME_ID}),
            frame_data,
            "low",
            "Read one caller-owned ephemeral browser frame.",
            rate_limit=low_read,
            idempotency_mode="disabled",
        ),
    ]


def _inspect_verb(rate_limit: dict[str, Any]) -> VerbSpec:
    coordinate = {"type": "integer", "minimum": 0, "maximum": MAX_COORDINATE}
    node = {
        "type": "object",
        "properties": {
            "node_id": {"type": "integer", "minimum": 1},
            "role": {"type": "string", "maxLength": 80},
            "name": {"type": "string", "maxLength": 240},
            "x": coordinate,
            "y": coordinate,
            "width": {"type": "integer", "minimum": 1, "maximum": MAX_COORDINATE},
            "height": {"type": "integer", "minimum": 1, "maximum": MAX_COORDINATE},
        },
        "required": ["node_id", "role", "name"],
        "additionalProperties": False,
    }
    return VerbSpec(
        "browser.inspect",
        "browser",
        schema(
            props={
                "name": NAME,
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_AX_NODES},
            }
        ),
        {
            "type": "object",
            "properties": {"nodes": {"type": "array", "maxItems": MAX_AX_NODES, "items": node}},
            "required": ["nodes"],
            "additionalProperties": False,
        },
        "low",
        "Inspect a bounded accessibility-tree projection.",
        rate_limit=rate_limit,
    )
