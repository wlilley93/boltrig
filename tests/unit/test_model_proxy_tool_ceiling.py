"""The model-call tool ceiling: what the cell may be offered, enforced on the wire.

Codex 0.144.3 offers exec_command/write_stdin/update_plan/request_user_input/
view_image on every turn and config.toml cannot suppress them, so the quarantined
read-only lane's "no effective tools" assertion is only true if the proxy makes it
true. These cases pin that behaviour.
"""

from __future__ import annotations

import json

import pytest

from boltrig.fleet.infrastructure.model_proxy_tool_ceiling import (
    MAX_MODEL_CALL_BODY_BYTES,
    ToolCallStreamGuard,
    ToolCeilingViolation,
    enforce_tool_ceiling,
)

_CODEX_TOOLS = [
    {"type": "function", "name": "exec_command"},
    {"type": "function", "name": "write_stdin"},
    {"type": "function", "name": "update_plan"},
    {"type": "function", "name": "request_user_input"},
    {"type": "function", "name": "view_image"},
]


def _body(payload: object) -> bytes:
    return json.dumps(payload).encode("utf-8")


def test_an_empty_ceiling_strips_every_codex_builtin_tool() -> None:
    """The read-only lane's real observed tool list must not survive the proxy."""

    body = _body({"model": "glm-4.6", "input": "hi", "tools": _CODEX_TOOLS})
    result = json.loads(enforce_tool_ceiling(body, frozenset()))
    assert "tools" not in result
    assert result["input"] == "hi"


def test_tool_choice_is_dropped_with_the_last_tool() -> None:
    body = _body({"input": "hi", "tools": _CODEX_TOOLS, "tool_choice": "auto"})
    result = json.loads(enforce_tool_ceiling(body, frozenset()))
    assert "tools" not in result and "tool_choice" not in result


def test_a_granted_tool_survives_and_the_rest_are_removed() -> None:
    """PR8's write phase widens by policy; partial ceilings must work exactly."""

    body = _body({"input": "hi", "tools": _CODEX_TOOLS})
    result = json.loads(enforce_tool_ceiling(body, frozenset({"update_plan"})))
    assert result["tools"] == [{"type": "function", "name": "update_plan"}]


def test_an_untouched_body_is_returned_byte_identical() -> None:
    """No tools to strip means no re-serialisation, so nothing else can drift."""

    body = _body({"input": "hi"})
    assert enforce_tool_ceiling(body, frozenset()) is body
    allowed = frozenset({"exec_command", "write_stdin", "update_plan",
                         "request_user_input", "view_image"})
    full = _body({"input": "hi", "tools": _CODEX_TOOLS})
    assert enforce_tool_ceiling(full, allowed) is full


def test_an_empty_body_passes_through() -> None:
    assert enforce_tool_ceiling(b"", frozenset()) == b""


def test_an_unnamed_tool_entry_can_never_match_the_ceiling() -> None:
    body = _body({"input": "hi", "tools": [{"parameters": {}}, "exec_command"]})
    result = json.loads(enforce_tool_ceiling(body, frozenset({"exec_command"})))
    assert "tools" not in result


def test_a_builtin_tool_is_named_by_its_type_when_it_has_no_name() -> None:
    body = _body({"input": "hi", "tools": [{"type": "web_search"}]})
    assert enforce_tool_ceiling(body, frozenset({"web_search"})) is body
    assert "tools" not in json.loads(enforce_tool_ceiling(body, frozenset()))


def test_an_unparseable_body_is_refused_rather_than_forwarded() -> None:
    """Fail-closed: a tool set we cannot read is a tool set we cannot bound."""

    with pytest.raises(ToolCeilingViolation):
        enforce_tool_ceiling(b"{not json", frozenset())
    with pytest.raises(ToolCeilingViolation):
        enforce_tool_ceiling(b"\xff\xfe", frozenset())


def test_a_body_beyond_the_verifiable_cap_is_refused() -> None:
    with pytest.raises(ToolCeilingViolation):
        enforce_tool_ceiling(b"x" * (MAX_MODEL_CALL_BODY_BYTES + 1), frozenset())


def test_a_non_list_tools_key_is_refused() -> None:
    with pytest.raises(ToolCeilingViolation):
        enforce_tool_ceiling(_body({"tools": "exec_command"}), frozenset())


def test_a_non_object_json_body_is_forwarded_unchanged() -> None:
    body = _body(["ping"])
    assert enforce_tool_ceiling(body, frozenset()) is body


def test_the_stream_guard_refuses_an_unsolicited_tool_call() -> None:
    """Exclusivity limb (c): the gateway must not confer a tool we never offered."""

    guard = ToolCallStreamGuard(frozenset())
    guard.inspect(b'data: {"type":"response.output_text.delta","delta":"hi"}\n\n')
    with pytest.raises(ToolCeilingViolation):
        guard.inspect(
            b'data: {"type":"response.output_item.added","item":'
            b'{"type":"function_call","name":"exec_command"}}\n\n'
        )


def test_the_stream_guard_sees_a_marker_split_across_chunks() -> None:
    """A chunk boundary must not be a way through the guard."""

    guard = ToolCallStreamGuard(frozenset())
    guard.inspect(b'data: {"item":{"type":"functio')
    with pytest.raises(ToolCeilingViolation):
        guard.inspect(b'n_call","name":"exec_command"}}')


def test_the_stream_guard_allows_a_granted_tool_and_bars_the_rest() -> None:
    """PR8's write phase widens by policy here too, not by disabling the guard."""

    guard = ToolCallStreamGuard(frozenset({"update_plan"}))
    guard.inspect(b'{"item":{"type":"function_call","name":"update_plan"}}')
    with pytest.raises(ToolCeilingViolation):
        guard.inspect(b'{"item":{"type":"function_call","name":"exec_command"}}')


def test_the_stream_guard_passes_ordinary_text() -> None:
    guard = ToolCallStreamGuard(frozenset())
    for chunk in (b'data: {"object":"response",', b'"output":[{"type":"message"}]}'):
        guard.inspect(chunk)
