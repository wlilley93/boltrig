"""The model-call tool ceiling: what the cell may be offered + how the MCP
namespace is bridged, enforced on the wire.

Two jobs live in this one chokepoint (VJS-CC-VJS 4):

1. Codex 0.144.3 offers exec_command/write_stdin/update_plan/request_user_input/
   view_image on every turn and config.toml cannot suppress them, so the
   quarantined read-only lane's "no effective tools" assertion is only true if the
   proxy makes it true.
2. Codex presents the kernel MCP server as ONE ``{"type":"namespace",
   "name":"mcp__boltrig","tools":[...]}`` entry, which a namespace-blind gateway
   collapses into a single opaque tool. ``enforce_tool_ceiling`` FLATTENS the
   namespace on the request (nested verbs spread as top-level function tools) and
   :class:`CodexResponseStreamProcessor` REATTACHES ``namespace="mcp__boltrig"``
   onto each returned ``function_call`` so Codex's strict ToolName match resolves.

These cases pin both behaviours.
"""

from __future__ import annotations

import json

import pytest

from boltrig.fleet.infrastructure.codex_kernel_tools_phase import (
    CODEX_MCP_NAMESPACE_NAME,
)
from boltrig.fleet.infrastructure.model_proxy_tool_ceiling import (
    MAX_MODEL_CALL_BODY_BYTES,
    CodexResponseStreamProcessor,
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

# The kernel MCP namespace entry as Codex presents it: nested verbs are bare
# sanitized function tools (``opbox.matter.list`` -> ``opbox_matter_list``).
_NESTED = [
    {"type": "function", "name": "opbox_matter_list", "description": "list", "parameters": {}},
    {"type": "function", "name": "knowledge_search", "description": "search", "parameters": {}},
]
_NAMESPACE = {"type": "namespace", "name": CODEX_MCP_NAMESPACE_NAME, "tools": _NESTED}


def _body(payload: object) -> bytes:
    return json.dumps(payload).encode("utf-8")


# --- request-side ceiling on Codex built-ins --------------------------------


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
    """No tools to change means no re-serialisation, so nothing else can drift."""

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


# --- request-side MCP namespace flatten -------------------------------------


def test_the_mcp_namespace_is_flattened_to_top_level_function_tools() -> None:
    """A namespace-blind gateway collapses the namespace; flattening spreads its
    ceiling-kept verbs as ordinary top-level function tools it forwards intact."""

    allowed = frozenset({"opbox_matter_list", "knowledge_search"})
    result = json.loads(enforce_tool_ceiling(_body({"input": "hi", "tools": [_NAMESPACE]}), allowed))
    assert result["tools"] == _NESTED  # spread as-is, bare-named, no namespace wrapper
    assert all(t["type"] == "function" for t in result["tools"])


def test_flatten_keeps_only_ceiling_verbs_from_the_namespace() -> None:
    allowed = frozenset({"opbox_matter_list"})
    result = json.loads(enforce_tool_ceiling(_body({"input": "hi", "tools": [_NAMESPACE]}), allowed))
    assert [t["name"] for t in result["tools"]] == ["opbox_matter_list"]


def test_an_empty_ceiling_strips_the_whole_namespace() -> None:
    """The read-only lane: no verb from the namespace survives."""

    result = json.loads(enforce_tool_ceiling(_body({"input": "hi", "tools": [_NAMESPACE]}), frozenset()))
    assert "tools" not in result


def test_a_foreign_namespace_contributes_nothing() -> None:
    """Only the pinned boltrig namespace is flattened; any other is dropped whole."""

    foreign = {"type": "namespace", "name": "mcp__other", "tools": _NESTED}
    allowed = frozenset({"opbox_matter_list", "knowledge_search"})
    result = json.loads(enforce_tool_ceiling(_body({"input": "hi", "tools": [foreign]}), allowed))
    assert "tools" not in result


def test_flatten_dedupes_a_verb_offered_both_bare_and_namespaced() -> None:
    bare = {"type": "function", "name": "opbox_matter_list", "description": "list", "parameters": {}}
    allowed = frozenset({"opbox_matter_list"})
    body = _body({"input": "hi", "tools": [bare, _NAMESPACE]})
    result = json.loads(enforce_tool_ceiling(body, allowed))
    assert [t["name"] for t in result["tools"]] == ["opbox_matter_list"]


# --- request-side fail-closed guards ----------------------------------------


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


# --- response-side namespace reattach + ceiling enforcement -----------------


def _event(item: dict) -> bytes:
    frame = {"type": "response.output_item.added", "item": item}
    return b"data: " + json.dumps(frame).encode("utf-8") + b"\n\n"


def test_a_returned_function_call_gets_the_namespace_reattached() -> None:
    """The request was flattened, so the model returns a bare name Codex cannot
    resolve; the processor reattaches ``mcp__boltrig`` for the strict match."""

    processor = CodexResponseStreamProcessor(frozenset({"opbox_matter_list"}))
    out = processor.feed(_event({"type": "function_call", "name": "opbox_matter_list", "arguments": "{}"}))
    out += processor.finish()
    payload = json.loads(out.split(b"data: ", 1)[1].split(b"\n\n", 1)[0])
    call = payload["item"]
    assert call["name"] == "opbox_matter_list"
    assert call["namespace"] == CODEX_MCP_NAMESPACE_NAME


def test_a_crlf_delimited_stream_is_reassembled_and_reattached() -> None:
    """A gateway/provider using CRLF blank-line terminators (\\r\\n\\r\\n, which
    contains no \\n\\n) must not silently break the lane: the event is still
    reassembled and the namespace reattached, and a plain-text CRLF event before
    it passes through intact."""

    processor = CodexResponseStreamProcessor(frozenset({"opbox_matter_list"}))
    text = b'data: {"type":"response.output_text.delta","delta":"hi"}\r\n\r\n'
    call = (
        b"data: "
        + json.dumps({"type": "response.output_item.added",
                      "item": {"type": "function_call", "name": "opbox_matter_list", "arguments": "{}"}}).encode()
        + b"\r\n\r\n"
    )
    out = processor.feed(text) + processor.feed(call) + processor.finish()
    assert text in out  # the text event survives byte-for-byte
    # the function_call event was found (despite CRLF) and got the namespace
    rewritten = out.split(b"data: ", 2)[2]
    item = json.loads(rewritten.split(b"\r\n\r\n", 1)[0])["item"]
    assert item["name"] == "opbox_matter_list"
    assert item["namespace"] == CODEX_MCP_NAMESPACE_NAME


def test_a_returned_call_outside_the_ceiling_is_refused() -> None:
    """Enforcement runs on the response too: the gateway must not confer a tool we
    never offered (an unsolicited function_call would still be executed)."""

    processor = CodexResponseStreamProcessor(frozenset({"opbox_matter_list"}))
    with pytest.raises(ToolCeilingViolation):
        processor.feed(_event({"type": "function_call", "name": "exec_command", "arguments": "{}"}))


def test_an_empty_ceiling_refuses_any_returned_call() -> None:
    processor = CodexResponseStreamProcessor(frozenset())
    with pytest.raises(ToolCeilingViolation):
        processor.feed(_event({"type": "function_call", "name": "opbox_matter_list", "arguments": "{}"}))


def test_an_already_qualified_call_is_accepted_and_bared() -> None:
    """Defensive: a namespace-qualified return maps back to its bare ceiling verb."""

    processor = CodexResponseStreamProcessor(frozenset({"opbox_matter_list"}))
    qualified = f"{CODEX_MCP_NAMESPACE_NAME}__opbox_matter_list"
    out = processor.feed(_event({"type": "function_call", "name": qualified, "arguments": "{}"}))
    out += processor.finish()
    call = json.loads(out.split(b"data: ", 1)[1].split(b"\n\n", 1)[0])["item"]
    assert call["name"] == "opbox_matter_list"
    assert call["namespace"] == CODEX_MCP_NAMESPACE_NAME


def test_ordinary_text_events_pass_through_byte_for_byte() -> None:
    processor = CodexResponseStreamProcessor(frozenset({"opbox_matter_list"}))
    event = b'data: {"type":"response.output_text.delta","delta":"hi"}\n\n'
    assert processor.feed(event) == event
    assert processor.finish() == b""


def test_a_function_call_split_across_chunks_is_reassembled_and_rewritten() -> None:
    """A chunk boundary inside the frame must not defeat the rewrite."""

    processor = CodexResponseStreamProcessor(frozenset({"opbox_matter_list"}))
    event = _event({"type": "function_call", "name": "opbox_matter_list", "arguments": "{}"})
    split = len(event) // 2
    out = processor.feed(event[:split]) + processor.feed(event[split:]) + processor.finish()
    call = json.loads(out.split(b"data: ", 1)[1].split(b"\n\n", 1)[0])["item"]
    assert call["namespace"] == CODEX_MCP_NAMESPACE_NAME


def test_a_stream_ending_mid_tool_call_event_is_refused() -> None:
    """A trailing fragment still carrying a tool-call marker cannot be verified
    whole, so it is refused rather than relayed unchecked."""

    processor = CodexResponseStreamProcessor(frozenset({"opbox_matter_list"}))
    processor.feed(b'data: {"item":{"type":"function_call","name":"opbox_matter_list"')
    with pytest.raises(ToolCeilingViolation):
        processor.finish()


def test_a_done_frame_ends_the_stream_cleanly() -> None:
    processor = CodexResponseStreamProcessor(frozenset())
    assert processor.feed(b"data: [DONE]\n\n") == b"data: [DONE]\n\n"
    assert processor.finish() == b""
