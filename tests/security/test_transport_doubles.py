"""A stand-in for the pinned HTTP client must BE an httpx client.

THE DEFECT THIS EXISTS FOR, measured 2026-08-18. The MCP transport moved from
``client.post`` to ``bounded_http_response``, which streams a bounded body via
``build_request``/``send``. Four test files replaced ``pinned_async_client`` with
hand-written objects whose whole surface was ``async def post(self, url, json,
headers)``. They could not express the new seam, so they stopped resembling the
thing they replaced - and they did not say so. Discovery broke, and the failure
surfaced two steps away as "MCP server must be probed before activation":
twelve red tests whose names took three OOM-killed suite runs to even learn.

`grep -rln "async def post(self, url" tests/` found the whole blast radius in
one command, after the fact. This is that grep, before the fact.

THE RULE. A test that REPLACES ``egress.pinned_async_client`` hands back
something backed by ``httpx.MockTransport``. A MockTransport cannot drift from
httpx because it is httpx: when production changes how it reads a response, the
double follows for free, and when it genuinely cannot, the test fails loudly at
the seam rather than quietly two modules away.

WHAT THIS DELIBERATELY DOES NOT SAY. It does not forbid ``async def post`` in a
test - plenty of doubles legitimately have one and stand in for something that
is not an HTTP client. It does not touch a test that CALLS the real
``pinned_async_client`` (``test_egress_pinning`` must, since pinning is its
subject), nor one that patches a different function such as
``pinned_async_client_for_ip``. The rule is about one substitution, because that
is the one that silently rotted.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_TESTS = _REPO / "tests"

# An assignment or a monkeypatch OF the seam itself, with a word boundary so
# `pinned_async_client_for_ip` (a different function, patched by the worker
# network-policy tests) is not swept in.
_REPLACES_SEAM = re.compile(
    r"""(?x)
    (?: setattr \s* \( [^)]*? \b pinned_async_client \b (?! _ )   # monkeypatch.setattr(..., "pinned_async_client", ...)
      | \b pinned_async_client \b (?! _ ) \s* =                   # egress.pinned_async_client = ...
    )
    """
)

# THE SOLE SANCTIONED ESCAPE, and it is meant to be uncomfortable to grow. A file
# here must say why a real httpx client cannot stand in for the seam it replaces.
_DOCUMENTED_EXCEPTIONS: dict[str, str] = {}


def _files_replacing_the_seam() -> list[tuple[Path, str]]:
    found = []
    for path in sorted(_TESTS.rglob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        if _REPLACES_SEAM.search(text):
            found.append((path, text))
    return found


@pytest.mark.security
def test_the_gate_can_see_the_files_it_judges():
    """A sweep that matched nothing would make every assertion below vacuous."""
    found = _files_replacing_the_seam()
    assert len(found) >= 4, (
        f"scanned nothing useful: {_TESTS} yielded {len(found)} file(s) replacing "
        "pinned_async_client, and the assertion below iterates over exactly those"
    )


@pytest.mark.security
def test_every_pinned_client_double_is_a_real_httpx_transport():
    offences = []
    for path, text in _files_replacing_the_seam():
        relative = str(path.relative_to(_REPO))
        if relative in _DOCUMENTED_EXCEPTIONS:
            continue
        if "httpx.MockTransport" in text:
            continue
        offences.append(
            f"{relative}: replaces egress.pinned_async_client with a double that is "
            f"not backed by httpx.MockTransport. A hand-written client stops "
            f"resembling the seam the day production reads a response differently, "
            f"and says nothing when it does"
        )
    assert not offences, "hand-rolled pinned-client doubles:\n  " + "\n  ".join(offences)
