from __future__ import annotations

import asyncio
import logging

import pytest

from boltrig.fleet.infrastructure import codex_protocol as wire
from boltrig.fleet.infrastructure.codex_stdio_transport import (
    EXIT_STATUS_UNKNOWN,
    STDIO_STREAM_LIMIT,
    CodexProcessExitedError,
    CodexStdioTransport,
    classify_codex_stderr,
)
from tests.unit.codex_process_fakes import FakeProcess


def test_classify_codex_stderr_reports_labels_only_never_content() -> None:
    """The teardown classifier surfaces codex's own stage tokens as stable labels
    and NEVER any surrounding text (which could carry echoed tool arguments)."""
    tail = (
        b"2026 codex_core::tools: unsupported call for mcp__boltrig args={\"secret\":\"x\"}\n"
        b"item/tool/requestUserInput questions=[...]\n"
    )
    labels = classify_codex_stderr(tail)
    assert labels == ("approval-requested", "tool-call-unsupported")
    # Content-free: no fragment of the (potentially sensitive) line survives.
    joined = "".join(labels)
    assert "secret" not in joined and "mcp__boltrig" not in joined and "questions" not in joined


def test_classify_codex_stderr_is_empty_for_ordinary_output() -> None:
    assert classify_codex_stderr(b"") == ()
    assert classify_codex_stderr(b"just some ordinary INFO logging with no markers\n") == ()


def test_classify_codex_stderr_flags_a_rust_panic() -> None:
    assert classify_codex_stderr(b"thread 'main' panicked at 'boom'") == ("panic", "thread-panic")


async def test_stderr_markers_accumulate_and_survive_high_volume() -> None:
    """Markers are accumulated across the WHOLE stderr (not a bounded tail), so no
    marker is lost to volume: an early marker and a late one both survive even with
    lots of noise between them, and only the small label set is retained."""
    process = FakeProcess()
    transport = make_transport(process)
    process.feed_stderr(b"unsupported call EARLY\n")
    process.feed_stderr(b"x" * (128 * 1024))  # far more than any tail cap
    process.feed_stderr(b"thread 'main' panicked LATE\n")
    process.exit(0)
    await transport.wait_stderr_drained()

    markers = transport.stderr_markers
    assert "tool-call-unsupported" in markers  # early marker NOT lost (Finding 2)
    assert "thread-panic" in markers  # and the late one


async def test_a_marker_split_across_stderr_chunks_is_still_caught() -> None:
    """A token straddling two reads is bridged by the carry, so it is not missed."""
    process = FakeProcess()
    transport = make_transport(process)
    process.feed_stderr(b"prefix requestUser")  # first half of requestUserInput
    process.feed_stderr(b"Input more\n")  # second half in the next chunk
    process.exit(0)
    await transport.wait_stderr_drained()
    assert "approval-requested" in transport.stderr_markers


def make_transport(
    process: FakeProcess,
    *,
    write_timeout: float = 0.1,
    close_timeout: float = 0.01,
    terminate_timeout: float = 0.01,
    kill_timeout: float = 0.01,
) -> CodexStdioTransport:
    return CodexStdioTransport(
        process,
        write_timeout=write_timeout,
        close_timeout=close_timeout,
        terminate_timeout=terminate_timeout,
        kill_timeout=kill_timeout,
    )


async def test_write_is_one_utf8_jsonl_frame_and_concurrent_writes_do_not_interleave() -> None:
    process = FakeProcess()
    gate = asyncio.Event()
    process.stdin.drain_gate = gate
    transport = make_transport(process)

    first = asyncio.create_task(transport.write_line('{"id":1}'))
    await asyncio.sleep(0)
    second = asyncio.create_task(transport.write_line('{"id":2}'))
    await asyncio.sleep(0)

    assert process.stdin.writes == [b'{"id":1}\n']
    gate.set()
    await asyncio.gather(first, second)
    assert process.stdin.writes == [b'{"id":1}\n', b'{"id":2}\n']
    await transport.aclose()


async def test_write_drain_and_lock_wait_are_bounded() -> None:
    process = FakeProcess()
    process.stdin.drain_gate = asyncio.Event()
    transport = make_transport(process, write_timeout=0.01)
    first = asyncio.create_task(transport.write_line("{}"))
    await asyncio.sleep(0)

    with pytest.raises(wire.CodexTransportError, match="write failed"):
        await transport.write_line("{}")
    with pytest.raises(wire.CodexTransportError, match="write failed"):
        await first
    await transport.aclose()


async def test_read_returns_one_line_and_rejects_oversize_before_codec() -> None:
    process = FakeProcess()
    transport = make_transport(process)
    process.feed_stdout(b'{"method":"ready","params":{}}\n')

    assert await transport.read_line(wire.MAX_LINE_BYTES) == '{"method":"ready","params":{}}'

    process.feed_stdout(b"x" * (wire.MAX_LINE_BYTES + 1) + b"\n")
    with pytest.raises(wire.CodexTransportError, match="byte limit"):
        await transport.read_line(wire.MAX_LINE_BYTES)
    await transport.aclose()


async def test_read_rejects_wrong_bound_invalid_utf8_and_eof_without_payloads() -> None:
    process = FakeProcess()
    transport = make_transport(process)
    with pytest.raises(ValueError, match="exactly match"):
        await transport.read_line(1024)

    process.feed_stdout(b"\xff\n")
    with pytest.raises(wire.CodexTransportError, match="UTF-8"):
        await transport.read_line(wire.MAX_LINE_BYTES)

    process.exit(23)
    with pytest.raises(CodexProcessExitedError) as captured:
        await transport.read_line(wire.MAX_LINE_BYTES)
    assert captured.value.returncode == 23
    assert "23" in str(captured.value)
    await transport.aclose()


async def test_stderr_is_continuously_drained_without_retaining_secret_text() -> None:
    process = FakeProcess()
    transport = make_transport(process)
    secret = b"provider-secret-that-must-not-be-retained"

    process.feed_stderr(secret * 2000)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert not process.stderr._buffer  # noqa: SLF001 - verifies discard-only fake stream
    assert secret.decode() not in repr(transport)
    process.exit(1)
    await transport.wait_stderr_drained()
    await transport.aclose()


async def test_close_escalates_stdin_then_terminate_then_kill_with_bounds() -> None:
    process = FakeProcess(
        exit_on_stdin_close=False,
        exit_on_terminate=False,
        exit_on_kill=True,
    )
    transport = make_transport(process)

    await transport.aclose()

    assert process.stdin.closed
    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert process.returncode == -9
    assert transport.closed


async def test_cancelling_close_still_kills_and_reaps_the_owned_process() -> None:
    process = FakeProcess(exit_on_stdin_close=False, exit_on_terminate=False)
    transport = make_transport(process, close_timeout=10.0, terminate_timeout=10.0)
    closing = asyncio.create_task(transport.aclose())
    await asyncio.sleep(0)

    closing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await closing

    assert process.kill_calls == 1
    assert process.returncode == -9


def test_subprocess_stream_limit_is_the_exact_protocol_allocation_bound() -> None:
    assert STDIO_STREAM_LIMIT == wire.MAX_LINE_BYTES


async def test_a_clean_adopted_cell_teardown_is_not_warned_about(caplog) -> None:
    """An adopted cell is reaped by the spawner, so its status is ALWAYS the
    unknown sentinel. A clean teardown must therefore stay quiet - otherwise
    every healthy turn warns and the degraded-cell signal is worthless."""
    process = FakeProcess()
    transport = make_transport(process)
    process.exit(EXIT_STATUS_UNKNOWN)
    with caplog.at_level(logging.WARNING):
        await transport.aclose()
    assert "codex cell teardown" not in caplog.text


async def test_a_marker_still_warns_even_on_the_unknown_status(caplog) -> None:
    """The sentinel silences the STATUS, never the diagnosis: a cell that hit a
    codex-internal marker is still surfaced, labels only."""
    process = FakeProcess()
    transport = make_transport(process)
    process.feed_stderr(b"thread 'main' panicked at 'boom'\n")
    process.exit(EXIT_STATUS_UNKNOWN)
    await transport.wait_stderr_drained()
    with caplog.at_level(logging.WARNING):
        await transport.aclose()
    assert "codex cell teardown" in caplog.text
    assert "thread-panic" in caplog.text
    assert "boom" not in caplog.text  # labels only, never the line
