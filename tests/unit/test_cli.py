"""Security-sensitive command-line defaults."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from boltrig.api.cli import main


@pytest.mark.invariant("SEC-135")
@pytest.mark.parametrize(
    ("argv", "expected_host"),
    [
        (["serve"], "127.0.0.1"),
        (["serve", "--host", "0.0.0.0"], "0.0.0.0"),
    ],
)
def test_serve_is_loopback_only_unless_host_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    expected_host: str,
) -> None:
    calls: list[tuple[str, str, int]] = []
    fake_uvicorn = SimpleNamespace(
        run=lambda app, *, host, port: calls.append((app, host, port))
    )
    monkeypatch.setitem(__import__("sys").modules, "uvicorn", fake_uvicorn)

    assert main(argv) == 0
    assert calls == [("boltrig.api.asgi:app", expected_host, 8000)]
