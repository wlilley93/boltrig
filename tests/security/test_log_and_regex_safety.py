"""A caller-supplied value must not be able to forge a log record or stall a request.

Both defects were found by CodeQL on the capability-doctrine integration and both
are in code that integration introduced:

- ``py/polynomial-redos`` (high) in ``boltrig/kernel/idempotency.py``. The
  acronym-aware key normaliser was written with a greedy ``([A-Z]+)([A-Z][a-z])``,
  which backtracks quadratically on a run of capitals with no lowercase after
  it. The input is a KEY OF AN ADAPTER'S OUTPUT, so an external service picks it.
- ``py/log-injection`` (medium x5) in ``boltrig/adapters/egress.py`` and
  ``boltrig/kernel/dispatch.py``.

Each test here fails against the code as it was, not merely passes against the
code as it is; the ReDoS one asserts a time bound with a wide margin so it is a
real signal rather than a flake.
"""

from __future__ import annotations

import logging
import time

import pytest

from boltrig.kernel.idempotency import sensitive_key
from boltrig.log_safety import log_safe


@pytest.mark.security
def test_the_key_normaliser_is_linear_in_the_length_of_a_hostile_key() -> None:
    # The exact shape that made the old pattern quadratic: capitals, no
    # lowercase, so `[A-Z]+` backtracks through every split from every start.
    # Measured on the old regex: 49ms at 2k, 842ms at 8k, 13.6s at 32k. The new
    # one is 2ms at 32k. A 2s ceiling is ~1000x the observed cost and still
    # nowhere near the old value, so this cannot pass by accident on a slow box.
    hostile = "A" * 32_000
    started = time.perf_counter()
    sensitive_key(hostile)
    elapsed = time.perf_counter() - started
    assert elapsed < 2.0, f"key normalisation took {elapsed:.1f}s on a 32k key"


@pytest.mark.security
def test_the_normaliser_still_splits_acronyms_the_way_the_greedy_pattern_did() -> None:
    # Making it linear must not quietly change what it classifies. These are the
    # cases the greedy version was introduced FOR: an adapter returning "APIKey"
    # has to be recognised as sensitive, which the pre-acronym version missed.
    for key in ("APIKey", "apiKey", "api_key", "X-API-Key", "userAPIKey"):
        assert sensitive_key(key), key
    for key in ("region", "APIVersion", "count", "modelName"):
        assert not sensitive_key(key), key


@pytest.mark.security
@pytest.mark.parametrize(
    "hostile",
    [
        "https://a\nJan 01 00:00:00 kernel: egress allowed for https://evil.example",
        "https://a\r\nforged",
        # Escapes, never the characters themselves. The first draft carried
        # them literally, and what landed in the file was U+0085 where U+2029
        # was meant - two codepoints that look identical in an editor, in a
        # list whose whole job is to name the codepoint under test.
        "https://a\u2028forged",  # LINE SEPARATOR: str.splitlines() breaks on it
        "https://a\u0085forged",  # NEL, a C1 control: splitlines() breaks on it too
        "https://a\u2029forged",  # PARAGRAPH SEPARATOR: and on this
        "https://a\x1b[2Koverwritten",  # repaints the line in a terminal
        "https://a\x00b",
    ],
)
def test_log_safe_leaves_exactly_one_record(hostile: str) -> None:
    rendered = log_safe(hostile)
    # splitlines, not a CR/LF check: it is the function a reader would use, and
    # it breaks on more characters than a CR/LF filter removes.
    assert len(rendered.splitlines()) == 1, rendered
    assert "\n" not in rendered and "\r" not in rendered


@pytest.mark.security
def test_log_safe_bounds_length_and_says_that_it_did() -> None:
    rendered = log_safe("x" * 5_000)
    assert len(rendered) < 300
    assert "5000 chars" in rendered, "a silent truncation misreports what arrived"


@pytest.mark.security
def test_log_safe_passes_an_ordinary_value_through_untouched() -> None:
    # A sanitiser that mangles the normal case gets removed by the next person.
    for value in ("https://api.example.com/v1/chat", "runs.create", "denied: host not allowed"):
        assert log_safe(value) == value


@pytest.mark.security
def test_the_egress_refusal_record_cannot_be_forged(caplog) -> None:
    from boltrig.adapters.egress import EgressBlocked, vet_url

    hostile = "http://127.0.0.1\nJan 01 00:00:00 boltrig.egress: egress allowed for x"
    with caplog.at_level(logging.WARNING, logger="boltrig.egress"):
        with pytest.raises(EgressBlocked):
            vet_url(hostile)

    assert caplog.records, "the refusal must still be logged"
    for record in caplog.records:
        assert len(record.getMessage().splitlines()) == 1, record.getMessage()


@pytest.mark.security
def test_no_egress_log_call_interpolates_a_raw_caller_value() -> None:
    """Guard the pair, not the instance.

    CodeQL flagged one of the two identical egress refusal lines. Fixing only
    that one leaves the other reachable by the same input, and the alert list
    would have gone quiet either way. This walks the AST rather than matching
    text, so it does not fail on reindentation and does not pass on a call it
    failed to find: it asserts the call count too.
    """
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    tree = ast.parse((root / "boltrig/adapters/egress.py").read_text(encoding="utf-8"))

    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "_egress_log"
    ]
    assert len(calls) == 2, f"expected 2 egress log calls, found {len(calls)}"

    for call in calls:
        # arg 0 is the format string and stays literal; every %-arg after it
        # must arrive through log_safe().
        for arg in call.args[1:]:
            assert isinstance(arg, ast.Call), ast.dump(arg)
            assert isinstance(arg.func, ast.Name) and arg.func.id == "log_safe", (
                f"unsanitised value in an egress log call: {ast.unparse(arg)}"
            )
