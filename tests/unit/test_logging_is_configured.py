"""The kernel process configured no logging at all, and that hid a live incident.

``uvicorn boltrig.api.asgi:app`` is how the kernel runs. Uvicorn's LOGGING_CONFIG
carries no ``root`` key and ``asgi.py`` never touched logging, so root kept its
default WARNING level and - decisively - ZERO handlers.

Two consequences, both load-bearing on 2026-07-27:

  * all 35 ``log.info`` / 7 ``log.debug`` calls in ``boltrig/`` were discarded at
    ``isEnabledFor`` before reaching a handler, so a boot that wired an adapter and
    one that silently skipped it produced identical output: nothing;
  * surviving WARNINGs fell through to ``logging.lastResort``, a bare StreamHandler
    with NO formatter - no timestamp, no level, no logger name. A tenant's agent
    failed every turn for an hour and emitted eight identical unattributed lines.

A level assertion alone would not have caught the second one, so these tests assert
the HANDLER and its FORMATTER, not just the level.
"""

from __future__ import annotations

import logging

import pytest

from boltrig.api.logging_config import DEFAULT_LEVEL, FORMAT, configure_logging, resolve_level


@pytest.fixture(autouse=True)
def _restore_root_logging():
    root = logging.getLogger()
    before_handlers, before_level = list(root.handlers), root.level
    yield
    root.handlers[:] = before_handlers
    root.setLevel(before_level)


def test_root_gets_a_real_handler_so_nothing_routes_through_lastresort() -> None:
    configure_logging()
    root = logging.getLogger()
    assert root.handlers, (
        "root has no handler, so records fall through to logging.lastResort, which "
        "has no formatter: no timestamp, no level name, no logger name"
    )
    assert all(h.formatter is not None for h in root.handlers), (
        "a handler with no formatter is how eight identical unattributed lines happened"
    )


def test_info_actually_reaches_a_handler_and_is_formatted() -> None:
    """The 42 sub-WARNING diagnostics in boltrig/ were dead before this.

    Captured with our OWN handler rather than caplog: ``configure_logging`` calls
    basicConfig(force=True), which removes every root handler including pytest's,
    so caplog would measure the teardown instead of the behaviour.
    """
    import io

    configure_logging()
    root = logging.getLogger()
    assert root.isEnabledFor(logging.INFO)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter(FORMAT))
    root.addHandler(handler)
    try:
        logging.getLogger("boltrig.test").info("boot detail")
    finally:
        root.removeHandler(handler)
    written = stream.getvalue()
    assert "boot detail" in written
    # The three fields whose absence made eight lines uncorrelatable.
    assert "INFO" in written and "boltrig.test" in written
    assert written.strip()[:4].isdigit(), f"no timestamp on the record: {written!r}"


def test_the_format_carries_what_correlation_needs() -> None:
    for field in ("%(asctime)s", "%(levelname)", "%(name)s", "%(message)s"):
        assert field in FORMAT, f"{field} missing: incidents cannot be correlated without it"


def test_an_unreadable_level_falls_back_rather_than_silencing_the_process() -> None:
    """A typo in BOLTRIG_LOG_LEVEL must not reproduce the blindness, quietly."""
    assert resolve_level("nonsense-value") == logging.INFO
    assert resolve_level(None) == logging.getLevelNamesMapping()[DEFAULT_LEVEL]
    assert resolve_level("warning") == logging.WARNING


def test_both_entrypoints_configure_logging_and_neither_rolls_its_own() -> None:
    """asgi.py and worker.py are one codebase; they had two different visibilities."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    for name in ("asgi.py", "worker.py"):
        src = (root / "boltrig" / "api" / name).read_text()
        assert "configure_logging()" in src, f"{name} does not configure logging"
        assert "basicConfig" not in src, (
            f"{name} rolls its own logging config; there must be exactly one"
        )
