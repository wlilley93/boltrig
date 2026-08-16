"""The invariants three dismissed CodeQL alerts depend on (#49, #50, #51).

A dismissal is a claim that the rule fired on something that cannot happen.
That claim decays: the code moves, and nothing re-checks it. These are the two
properties worth holding, written so a regression fails here rather than
quietly re-opening an alert nobody is watching for.

  #51  py/stack-trace-exposure, camera_agent_routes.py
       CodeQL sees `str(exc)` flow toward a response body. It cannot see that
       `_validation_reason()` tests membership in a frozenset and substitutes
       a fixed string otherwise, which truncates the flow. What must stay true
       is that EVERY argument to `_error()` is a literal or that reducer.

  #49  py/clear-text-storage-sensitive-data, desktop_session_auth.py
       A session secret in a Set-Cookie is how sessions work; the rule reads
       any cookie write as clear-text storage. The property actually worth
       holding is the one a careless edit would break: SameSite drops to
       "none" ONLY for an allow-listed desktop webview origin that is also
       configured, and only when the cookie is Secure.

  #50  js/file-system-race, tests/visual/sourceDigest.mjs
       lstat-then-read on a repo checkout, inside a test helper, with no
       privilege boundary and no second writer. A race there produces a digest
       mismatch -- a failing gate -- not a disclosure. There is no invariant to
       pin, so it has no test here, deliberately.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, cast

import pytest

from boltrig.api import desktop_session_auth as dsa
from boltrig.identity import SESSION_COOKIE

ROOT = Path(__file__).resolve().parents[2]
CAMERA_ROUTES = ROOT / "boltrig" / "kernel" / "camera_agent_routes.py"


# ------------------------------------------------------------------ #51
def _error_arguments() -> list[ast.expr]:
    tree = ast.parse(CAMERA_ROUTES.read_text(encoding="utf-8"))
    return [node.args[0] for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_error"
            and node.args]


def test_every_error_reason_is_a_literal_or_the_reducer() -> None:
    args = _error_arguments()
    assert len(args) >= 15, "expected the module to still route errors through _error"
    for arg in args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            continue
        ok = (isinstance(arg, ast.Call)
              and isinstance(arg.func, ast.Name)
              and arg.func.id == "_validation_reason")
        assert ok, (
            f"_error() at line {arg.lineno} is given something that is neither a "
            f"string literal nor _validation_reason(...); it may publish an "
            f"exception message")


def test_the_reducer_substitutes_anything_it_does_not_recognise() -> None:
    """The frozenset is what truncates the taint. If it ever stops being a
    membership test, the dismissal of #51 stops being true."""
    import importlib

    mod = importlib.import_module("boltrig.kernel.camera_agent_routes")
    leaky = ValueError("/Users/someone/secret/path.py line 40: connection refused")
    assert mod._validation_reason(leaky) == "invalid_request"
    known = next(iter(mod._VALIDATION_REASONS))
    assert mod._validation_reason(ValueError(known)) == known


# ------------------------------------------------------------------ #49
class _Req:
    """Only the one attribute the function reads. Typed as Any at the call
    sites below: these are deliberate stand-ins for starlette's Request and
    JSONResponse, and constructing the real ones would test starlette."""

    def __init__(self, origin: str | None) -> None:
        self.headers: dict[str, str] = {"origin": origin} if origin is not None else {}


@pytest.mark.parametrize("origin,configured,expected", [
    ("tauri://localhost", "tauri://localhost", True),
    ("https://tauri.localhost", "https://tauri.localhost", True),
    # allow-listed but NOT configured -- both halves are required
    ("tauri://localhost", "", False),
    ("tauri://localhost", "https://example.com", False),
    # configured but not allow-listed: an operator cannot widen this by env
    ("https://evil.example", "https://evil.example", False),
    ("http://localhost:5173", "http://localhost:5173", False),
    (None, "tauri://localhost", False),
])
def test_desktop_origin_needs_both_the_allowlist_and_the_config(
    monkeypatch: pytest.MonkeyPatch, origin: str | None, configured: str, expected: bool,
) -> None:
    monkeypatch.setenv("BOLTRIG_CORS_ORIGINS", configured)
    assert dsa._desktop_session_request(cast(Any, _Req(origin))) is expected


def test_samesite_none_requires_secure_and_a_desktop_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SameSite=None is the CSRF-relevant relaxation. Insecure transport must
    never reach it, whatever the origin claims."""
    monkeypatch.setenv("BOLTRIG_CORS_ORIGINS", "tauri://localhost")
    seen: list[dict[str, object]] = []

    class _Resp:
        def set_cookie(self, key: str, value: str, **kw: object) -> None:
            seen.append({"key": key, **kw})

    for secure, request, want in ((True, _Req("tauri://localhost"), "none"),
                                  (False, _Req("tauri://localhost"), "strict"),
                                  (True, _Req("https://evil.example"), "strict"),
                                  (True, None, "strict")):
        seen.clear()
        dsa.set_session_cookies(cast(Any, _Resp()), "secret", "csrf",
                                secure=secure, request=cast(Any, request))
        assert seen, "no cookies were set"
        assert {c["samesite"] for c in seen} == {want}, (
            f"secure={secure} origin={getattr(request, 'headers', {}).get('origin')} "
            f"gave {[c['samesite'] for c in seen]}, expected {want}")
        # The session cookie is httponly whatever else changes; the CSRF one is
        # readable by design, so assert per-cookie rather than over the set.
        session = next(c for c in seen if c["key"] == SESSION_COOKIE)
        assert session["httponly"] is True
        assert session["secure"] is secure
