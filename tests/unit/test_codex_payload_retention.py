"""Invariant: raw peer payloads never survive into decode errors or terminals.

The Codex App Server sends JSONL frames over a local peer transport. A
malformed or secret-shaped frame must be rejected without the raw line, its
fields, or any chained cause reaching an exception message or a traceback-held
frame that an error path could retain. These guards lock that property so it
cannot regress.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, cast

import pytest

from boltrig.fleet.infrastructure import codex_protocol as wire
from boltrig.fleet.infrastructure.codex_protocol import (
    MAX_LINE_BYTES,
    decode_message,
)
from boltrig.fleet.infrastructure.codex_runtime_actor import (
    CodexRuntimeActor,
    CodexRuntimeTerminal,
)

_SECRET = "sk-am 字 provider-secret-9f3a2b7c"  # mixed ASCII/multibyte, token-shaped


@pytest.mark.parametrize(
    "line",
    [
        # Invalid JSON object with the secret embedded as a bare token.
        "{" + _SECRET + "}",
        # Valid JSON shape but params is not an object.
        '{"method":"turn/started","params":' + json.dumps(_SECRET) + "}",
        # Duplicate keys carrying the secret.
        '{"method":"turn/started","method":"turn/started","params":{"q":'
        + json.dumps(_SECRET)
        + "}}",
        # Wrong envelope fields with the secret in a stray field.
        '{"method":"turn/started","params":{},"extra":' + json.dumps(_SECRET) + "}",
        # A valid-shaped notification so large it exceeds the line limit, with
        # the secret buried in oversized padding.
        '{"method":"turn/started","params":{"q":"'
        + ("x" * (MAX_LINE_BYTES + 64))
        + _SECRET
        + '"}}',
    ],
)
def test_decode_error_never_echoes_payload_or_carries_a_chained_cause(
    line: str,
) -> None:
    with pytest.raises(wire.MalformedMessageError) as raised:
        decode_message(line)
    message = str(raised.value)
    assert _SECRET not in message
    assert "provider-secret" not in message
    assert "9f3a2b7c" not in message
    # No chained cause may carry the raw candidate string or its parsed object
    # into a traceback-held frame. ``from None`` suppresses the parse error on
    # the JSON path; the byte-limit path is a fresh raise with no cause either.
    assert raised.value.__cause__ is None


def test_terminal_exception_message_is_sanitized_and_payload_free() -> None:
    terminal = CodexRuntimeTerminal("operation", "Codex notification pump failed")
    exception = terminal.exception()
    assert str(exception) == "Codex notification pump failed"
    assert _SECRET not in str(exception)
    assert "provider-secret" not in str(exception)
    # Every terminal category resolves to a bounded, server-owned message.
    for category in ("protocol", "binding", "closed", "operation"):
        each = CodexRuntimeTerminal(category, f"{category} cause").exception()
        assert _SECRET not in str(each)


@pytest.mark.asyncio
async def test_pump_crash_names_the_exception_type_without_leaking_its_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A live tenant's agent failed every turn and the log could not say why.

    `_run` caught `Exception` and discarded it, so a reset socket, a cell that
    died before its first frame, and a malformed frame all reported the identical
    eight words: "Codex notification pump failed". The terminal message must stay
    content-free (it travels to handovers and the audit record), but the operator
    log must name the exception TYPE, which is a class from our own stack.

    The type is the whole point, and str(exc)/exc_info are the whole risk: a
    JSONDecodeError carries the offending document in its args.
    """

    class _CellDiedCarryingASecret(RuntimeError):
        pass

    poisoned = _CellDiedCarryingASecret(_SECRET)

    class _Client:
        async def next_notification(self, timeout: float | None = None) -> object:
            raise poisoned

    terminals: list[CodexRuntimeTerminal] = []

    async def _on_terminal(_actor: object, terminal: CodexRuntimeTerminal) -> None:
        terminals.append(terminal)

    actor = CodexRuntimeActor(
        client=cast(Any, _Client()),
        translator=cast(Any, object()),
        on_terminal=_on_terminal,
        max_buffered_events=8,
    )
    with caplog.at_level(logging.WARNING):
        await actor._run()

    logged = caplog.text
    # The cause is now distinguishable...
    assert "_CellDiedCarryingASecret" in logged, (
        "the pump crash log does not name the exception type, so every cause "
        "reports the same eight words"
    )
    # ...and the exception's ARGS never reach the log or the terminal.
    assert _SECRET not in logged
    assert terminals and terminals[0].message == "Codex notification pump failed"
    assert _SECRET not in terminals[0].message


@pytest.mark.asyncio
async def test_an_expected_teardown_race_is_not_logged_as_a_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Observed live on 2026-07-28, one millisecond apart:

        codex runtime terminal: category=closed cause=Codex thread closed
        codex notification pump crashed: ...codex_protocol.ProtocolStateError

    The turn had ALREADY ended. The pump was blocked on next_notification() against
    a connection that had gone, and raised ProtocolStateError("connection is
    closed") on the way out. `fail` correctly declines to overwrite the first
    terminal, so the turn is recorded as closed, not failed.

    But logging that at WARNING fires on EVERY healthy turn, and an alarm that
    cries wolf on the happy path is the same blindness as no alarm at all. It is a
    WARNING only when the crash is the CAUSE.

    The terminal must be set WHILE the pump is awaiting - setting it first makes
    `_run` exit on its loop condition without ever calling the client, which is not
    the race.
    """

    class _ConnectionClosed(RuntimeError):
        pass

    released = asyncio.Event()

    class _Client:
        async def next_notification(self, timeout: float | None = None) -> object:
            await released.wait()
            raise _ConnectionClosed("connection is closed")

    async def _on_terminal(_a: object, _t: CodexRuntimeTerminal) -> None:
        return None

    actor = CodexRuntimeActor(
        client=cast(Any, _Client()),
        translator=cast(Any, object()),
        on_terminal=_on_terminal,
        max_buffered_events=8,
    )
    with caplog.at_level(logging.INFO):
        runner = asyncio.create_task(actor._run())
        await asyncio.sleep(0)  # let the pump reach its await
        await actor.fail(CodexRuntimeTerminal("closed", "Codex thread closed"))
        released.set()
        await asyncio.wait_for(runner, timeout=5)

    records = [r for r in caplog.records if "pump crashed" in r.getMessage()]
    assert records, "the crash is still recorded - it is downgraded, not hidden"
    assert all(r.levelno == logging.INFO for r in records), (
        "an expected teardown race logged at WARNING fires on every healthy turn"
    )
    assert "_ConnectionClosed" in caplog.text
