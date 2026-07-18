"""Invariant: raw peer payloads never survive into decode errors or terminals.

The Codex App Server sends JSONL frames over a local peer transport. A
malformed or secret-shaped frame must be rejected without the raw line, its
fields, or any chained cause reaching an exception message or a traceback-held
frame that an error path could retain. These guards lock that property so it
cannot regress.
"""

from __future__ import annotations

import json

import pytest

from boltrig.fleet.infrastructure import codex_protocol as wire
from boltrig.fleet.infrastructure.codex_protocol import (
    MAX_LINE_BYTES,
    decode_message,
)
from boltrig.fleet.infrastructure.codex_runtime_actor import CodexRuntimeTerminal

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
