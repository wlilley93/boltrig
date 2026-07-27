"""One Python version, declared in nine places, must be the same version (IAC-004).

WHY. Dependabot #3 proposed moving `deploy/kernel.Dockerfile` and
`deploy/fleet.Dockerfile` from Python 3.12 to 3.14. Its checks went green, and they
could not have gone any other way: the `Container (kernel)` and `Container (fleet)`
jobs BUILD the image, and every job that RUNS the test suite pins `python-version:
"3.12"`. So a green check would have proved the image assembles under 3.14 and said
nothing whatever about whether the code executes there. A 3.14-only regression -
a removed stdlib alias, a changed default, a C-extension wheel that does not exist
yet - would have reached production having passed everything.

The coupling was prose: nine declarations of "3.12" scattered across workflows, two
Dockerfiles, a third-party sidecar and three tool configs, held together by nobody
noticing. Prose is not enforcement, so this is the enforcement.

WHAT IT CHECKS. Every declaration agrees on ONE minor version, derived from the
files rather than restated here, so moving Python means moving all of them in one
change - which is the only shape in which "we run 3.N" can be true:

  * deploy/kernel.Dockerfile, deploy/fleet.Dockerfile - what the kernel and fleet
    images actually execute
  * services/channel_gateway/Dockerfile - the severed sidecar, whose requirements
    lock is compiled for a specific CPython and says so in its header
  * .github/workflows/ci.yml, security.yml - every `python-version:` that runs the
    suite or the source-security tools
  * pyproject.toml - `requires-python`, ruff's `target-version`, mypy's
    `python_version`

WHAT IT DOES NOT CHECK. That the version is a good choice, or that 3.N is
supported upstream. Only that the repository has ONE answer to "which Python",
instead of nine that happen to coincide.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]

_DOCKERFILES = (
    "deploy/kernel.Dockerfile",
    "deploy/fleet.Dockerfile",
    "services/channel_gateway/Dockerfile",
)
_WORKFLOWS = (".github/workflows/ci.yml", ".github/workflows/security.yml")

_FROM_PYTHON = re.compile(r"^FROM python:(\d+)\.(\d+)\.\d+-", re.MULTILINE)
_ACTION_PIN = re.compile(r'^\s*python-version:\s*"?(\d+)\.(\d+)"?\s*$', re.MULTILINE)


def _text(path: str) -> str:
    return (_REPO / path).read_text(encoding="utf-8")


def _declarations() -> dict[str, set[tuple[int, int]]]:
    """Every declared (major, minor), grouped by where it was found."""
    found: dict[str, set[tuple[int, int]]] = {}

    for name in _DOCKERFILES:
        hits = {(int(a), int(b)) for a, b in _FROM_PYTHON.findall(_text(name))}
        assert hits, f"{name} has no `FROM python:X.Y.Z-` line to read"
        found[name] = hits

    for name in _WORKFLOWS:
        hits = {(int(a), int(b)) for a, b in _ACTION_PIN.findall(_text(name))}
        assert hits, f"{name} pins no python-version"
        found[name] = hits

    pyproject = _text("pyproject.toml")
    requires = re.search(r'^requires-python\s*=\s*">=(\d+)\.(\d+)"', pyproject, re.MULTILINE)
    target = re.search(r'^target-version\s*=\s*"py(\d)(\d+)"', pyproject, re.MULTILINE)
    mypy = re.search(r'^python_version\s*=\s*"(\d+)\.(\d+)"', pyproject, re.MULTILINE)
    assert requires and target and mypy, "pyproject.toml is missing a python declaration"
    found["pyproject.toml requires-python"] = {(int(requires[1]), int(requires[2]))}
    found["pyproject.toml ruff target-version"] = {(int(target[1]), int(target[2]))}
    found["pyproject.toml mypy python_version"] = {(int(mypy[1]), int(mypy[2]))}
    return found


@pytest.mark.security
@pytest.mark.invariant("IAC-004")
def test_every_python_declaration_agrees_on_one_version() -> None:
    found = _declarations()
    versions = {v for hits in found.values() for v in hits}
    if len(versions) == 1:
        return

    lines = [
        f"  {'.'.join(str(p) for p in sorted(hits)[0]) if len(hits) == 1 else sorted(hits)}"
        f"  <- {where}"
        for where, hits in sorted(found.items())
    ]
    raise AssertionError(
        "the repository declares more than one Python version:\n"
        + "\n".join(lines)
        + "\n\nMove them together. An image running a Python the suite never "
        "executes means a green check proves the image BUILDS, not that the code "
        "RUNS. See this file's docstring."
    )


@pytest.mark.security
@pytest.mark.invariant("IAC-004")
def test_the_channel_gateway_lock_is_compiled_for_that_same_version() -> None:
    """The sidecar's lock records the CPython that resolved it, and it must match.

    Environment markers and wheel selection are fixed AT COMPILE TIME. Installing a
    3.12-resolved graph under a different interpreter with `--require-hashes` either
    fails on a missing wheel or, worse, succeeds while shipping a graph resolved for
    a Python that is no longer running. This is why dependabot #136 was refused.
    """
    header = _text("services/channel_gateway/requirements.txt")[:400]
    stated = re.search(r"autogenerated by pip-compile with Python (\d+)\.(\d+)", header)
    assert stated, "the channel-gateway lock does not record the Python that compiled it"
    image = _FROM_PYTHON.findall(_text("services/channel_gateway/Dockerfile"))
    assert (stated[1], stated[2]) in [(a, b) for a, b in image], (
        f"the lock was compiled with Python {stated[1]}.{stated[2]} but the image runs "
        f"{image}. Regenerate the lock under the interpreter the image ships."
    )
