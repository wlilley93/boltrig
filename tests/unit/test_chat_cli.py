"""Offline tests for ``boltrig chat`` (boltrig/api/chat_cli.py): the SSE event
parser and renderer, the gateway frame codec, slash-command and target
parsing, and config resolution order. The HTTP layer is exercised against an
httpx.MockTransport - no live kernel."""

from __future__ import annotations

import json

import httpx
import pytest

from boltrig.api import chat_cli
from boltrig.api.chat_cli import (
    ChatCliError,
    SseParser,
    clean_target,
    decode_frame,
    encode_frame,
    load_config,
    parse_command,
    render_event,
    resolve_setting,
)

# --- SSE parsing --------------------------------------------------------------


def _parse(lines: list[str]) -> list[dict]:
    parser = SseParser()
    events = [e for line in lines if (e := parser.feed(line)) is not None]
    if (tail := parser.flush()) is not None:
        events.append(tail)
    return events


def test_parse_sse_reads_canned_event_stream() -> None:
    lines = [
        'data: {"type": "message_start", "run_id": "r1", "conversation_id": "c1"}',
        "",
        'data: {"type": "text_delta", "delta": "hel"}',
        "",
        'data: {"type": "text_delta", "delta": "lo"}',
        "",
        'data: {"type": "message_end", "run_id": "r1"}',
        "",
    ]
    events = _parse(lines)
    assert [e["type"] for e in events] == [
        "message_start", "text_delta", "text_delta", "message_end",
    ]
    assert events[0]["conversation_id"] == "c1"


def test_parse_sse_handles_multiline_data_and_comments() -> None:
    lines = [
        ": a keep-alive comment",
        'data: {"type": "text_delta",',
        'data:  "delta": "hi"}',
        "",
    ]
    assert _parse(lines) == [{"type": "text_delta", "delta": "hi"}]


def test_parse_sse_drops_malformed_and_non_dict_payloads() -> None:
    lines = [
        "data: {not json",
        "",
        'data: ["a", "list"]',
        "",
        'data: {"type": "text_delta", "delta": "ok"}',  # no trailing blank line
    ]
    assert _parse(lines) == [{"type": "text_delta", "delta": "ok"}]


# --- rendering -----------------------------------------------------------------


def test_render_text_delta_streams_inline() -> None:
    assert render_event({"type": "text_delta", "delta": "hello"}) == "hello"
    assert render_event({"type": "reasoning_delta", "delta": "thinking"}) == "thinking"


def test_render_tool_call_is_a_compact_one_liner_with_arg_keys_only() -> None:
    out = render_event({
        "type": "tool_call", "tool": "fs.read",
        "args_summary": {"keys": ["path", "limit"]},
    })
    assert out == "\n[tool] fs.read(path, limit)\n"
    # the bounded chat stream never carries raw input; nothing to leak
    assert "input" not in (out or "")


def test_render_tool_result_one_liner() -> None:
    assert render_event({"type": "tool_result", "call_id": "k1", "status": "ok"}) \
        == "[tool] -> ok\n"


def test_render_hitl_is_prominent_and_carries_the_request_id() -> None:
    out = render_event({
        "type": "hitl", "hitl_request_id": "hitl-9", "kind": "approval",
        "question": "Approve fs.write?",
    })
    assert "hitl-9" in (out or "")
    assert "Approve fs.write?" in (out or "")
    assert "/approve hitl-9" in (out or "")
    assert "/deny hitl-9" in (out or "")


def test_render_question_surfaces_id_choices_and_answer_hint() -> None:
    out = render_event({
        "type": "question", "question_id": "q-3",
        "prompt": "Which env?", "choices": ["staging", "prod"],
    })
    assert "Which env?" in (out or "")
    assert "staging, prod" in (out or "")
    assert "/answer q-3" in (out or "")


def test_render_terminal_and_silent_events() -> None:
    assert render_event({"type": "cancelled", "run_id": "r1"}) == "\n(cancelled)\n"
    assert render_event({"type": "queued", "run_id": "r1"}) \
        == "\n(instruction queued behind the active turn)\n"
    assert render_event({"type": "message_end", "run_id": "r1"}) == "\n"
    assert "[subagent]" in (render_event(
        {"type": "subagent", "name": "researcher", "task": "dig"}) or "")
    for silent in (
        {"type": "message_start", "run_id": "r1", "conversation_id": "c1"},
        {"type": "heartbeat", "run_id": "r1"},
        {"type": "workflow_step", "step_id": "s1"},
        {"type": "something_new"},
    ):
        assert render_event(silent) is None


# --- slash commands and target slugs --------------------------------------------


def test_parse_command() -> None:
    assert parse_command("/approve hitl-1") == ("approve", "hitl-1")
    assert parse_command("/answer q-1 do  the thing") == ("answer", "q-1 do  the thing")
    assert parse_command("/quit") == ("quit", "")
    assert parse_command("just chat text") is None
    assert parse_command("// not a command") is None
    assert parse_command("/") is None


def test_clean_target_matches_the_kernel_slug_rule() -> None:
    assert clean_target("cos") == "cos"
    assert clean_target("tier2.researcher-1") == "tier2.researcher-1"
    assert clean_target("  ") is None
    assert clean_target("has spaces") is None
    assert clean_target("x" * 65) is None
    assert clean_target(None) is None


# --- the gateway frame codec -----------------------------------------------------


def test_frame_round_trip() -> None:
    line = encode_frame("cli", "hello", "cli-1")
    assert line.endswith(b"\n")
    assert decode_frame(line) == {"id": "cli-1", "sender": "cli", "text": "hello"}


def test_frame_carries_an_optional_target_slug() -> None:
    line = encode_frame("cli", "hi", "cli-2", target="cos")
    assert decode_frame(line)["target"] == "cos"  # type: ignore[index]


def test_decode_frame_drops_malformed_lines() -> None:
    assert decode_frame(b"{not json\n") is None
    assert decode_frame(b"\xff\xfe\n") is None
    assert decode_frame(b'"a string"\n') is None


# --- config resolution -----------------------------------------------------------


def test_load_config_missing_file_is_empty(tmp_path) -> None:
    assert load_config(str(tmp_path / "nope.toml")) == {}


def test_load_config_malformed_toml_is_a_clean_error(tmp_path) -> None:
    bad = tmp_path / "cli.toml"
    bad.write_text("token = [unclosed")
    with pytest.raises(ChatCliError):
        load_config(str(bad))


def test_resolve_setting_order_flag_beats_env_beats_config(tmp_path) -> None:
    cfg_file = tmp_path / "cli.toml"
    cfg_file.write_text('token = "from-config"\nserver = "http://cfg:1"\n')
    config = load_config(str(cfg_file))
    assert resolve_setting("from-flag", "from-env", config.get("token")) == "from-flag"
    assert resolve_setting(None, "from-env", config.get("token")) == "from-env"
    assert resolve_setting(None, None, config.get("token")) == "from-config"
    assert resolve_setting(None, None, None, "fallback") == "fallback"
    assert resolve_setting("  ", "", None) is None  # blanks never win


# --- the HTTP layer against a mock transport -------------------------------------


def _sse_body(events: list[dict]) -> bytes:
    return b"".join(f"data: {json.dumps(e)}\n\n".encode() for e in events)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_stream_turn_yields_events_and_sends_bearer_auth() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization", "")
        seen["body"] = request.content.decode()
        return httpx.Response(200, content=_sse_body([
            {"type": "message_start", "run_id": "r1", "conversation_id": "c1"},
            {"type": "text_delta", "delta": "hi"},
            {"type": "message_end", "run_id": "r1"},
        ]))

    async with _client(handler) as client:
        events = [
            e async for e in chat_cli.stream_turn(
                client, "http://kernel", "boltrig_pat_secret", "hello", "c0")
        ]
    assert [e["type"] for e in events] == ["message_start", "text_delta", "message_end"]
    assert seen["auth"] == "Bearer boltrig_pat_secret"
    assert json.loads(seen["body"]) == {"message": "hello", "conversation_id": "c0"}


async def test_stream_turn_202_queued_is_an_accepted_terminal_event() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, json={
            "status": "queued",
            "conversation_id": "c1",
            "message_id": "m2",
            "run_id": "r1",
        })

    async with _client(handler) as client:
        events = [
            e async for e in chat_cli.stream_turn(
                client, "http://kernel", "tok", "steer", "c1")
        ]
    assert events == [{
        "type": "queued",
        "conversation_id": "c1",
        "message_id": "m2",
        "run_id": "r1",
    }]


async def test_stream_turn_other_202_remains_a_clean_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            202, json={"status": "pending_human", "reason": "approval_required"})

    async with _client(handler) as client:
        with pytest.raises(ChatCliError, match=r"HTTP 202.*approval_required"):
            _ = [
                e async for e in chat_cli.stream_turn(
                    client, "http://kernel", "tok", "hi", "c1")
            ]


async def test_stream_turn_401_is_a_clean_error_that_never_carries_the_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"status": "error", "reason": "unauthorized"})

    async with _client(handler) as client:
        with pytest.raises(ChatCliError) as excinfo:
            _ = [
                e async for e in chat_cli.stream_turn(
                    client, "http://kernel", "boltrig_pat_secret", "hi", None)
            ]
    message = str(excinfo.value)
    assert "authentication failed" in message
    assert "boltrig_pat_secret" not in message


async def test_stream_turn_connection_failure_is_a_clean_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    async with _client(handler) as client:
        with pytest.raises(ChatCliError, match="cannot reach the kernel"):
            _ = [
                e async for e in chat_cli.stream_turn(
                    client, "http://kernel", "tok", "hi", None)
            ]


async def test_respond_hitl_posts_the_decision() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"status": "ok"})

    async with _client(handler) as client:
        result = await chat_cli.respond_hitl(
            client, "http://kernel", "tok", "hitl-9", "approve")
    assert result["status"] == "ok"
    assert seen["path"] == "/v1/hitl/hitl-9/respond"
    assert json.loads(seen["body"]) == {"decision": "approve", "notes": ""}


async def test_answer_question_posts_to_the_answer_route() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"status": "ok"})

    async with _client(handler) as client:
        await chat_cli.answer_question(client, "http://kernel", "tok", "q-3", "staging")
    assert seen["path"] == "/v1/hitl/q-3/answer"
    assert json.loads(seen["body"]) == {"answer": "staging"}


async def test_respond_hitl_conflict_is_a_clean_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"status": "error", "reason": "not_a_question"})

    async with _client(handler) as client:
        with pytest.raises(ChatCliError, match="not_a_question"):
            await chat_cli.answer_question(client, "http://kernel", "tok", "q-3", "x")
