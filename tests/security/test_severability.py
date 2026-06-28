"""Severability: the kernel and models import nothing from sibling estate kernels.

Machine-enforces directive D5 of [2026] VJS-CC NANKLE-CONSOLIDATION 001: Nankle
stays a clean, deletable boundary with zero code coupling to Hermes / Phoenix /
Opbox / Agent-libOS / VJS. This turns the "quarterly severability audit" into a
build-red check rather than a manual ritual.
"""

from __future__ import annotations

import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2] / "nankle"
_SCOPED = [_ROOT / "kernel", _ROOT / "models"]

# import tokens that would indicate coupling to a sibling estate kernel
_FORBIDDEN = re.compile(
    r"^\s*(?:from|import)\s+(hermes|phoenix|opbox|agent_libos|agentlibos|vjs)\b",
    re.IGNORECASE,
)

# Round Two: the kernel/models must not import Pi or the sidecar; the sidecar is
# reached over the wire only (SEC-28). Also forbid runtime-backbone specifics
# (hatchet, the fleet's pi_runtime) leaking into the core.
_FORBIDDEN_PI = re.compile(
    r"^\s*(?:from|import)\s+(.*\b)?(pi_runtime|pi_sidecar|hatchet|hatchet_sdk)\b",
    re.IGNORECASE,
)


def _python_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for scope in _SCOPED:
        files.extend(scope.rglob("*.py"))
    return files


def _scan(pattern: re.Pattern[str]) -> list[str]:
    offenders: list[str] = []
    for path in _python_files():
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.match(line):
                offenders.append(f"{path}:{n}: {line.strip()}")
    return offenders


@pytest.mark.security
def test_kernel_and_models_have_no_estate_coupling():
    offenders = _scan(_FORBIDDEN)
    assert not offenders, "estate-coupling imports found (D5 severability):\n" + "\n".join(
        offenders
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-28")
def test_kernel_and_models_have_no_pi_or_sidecar_coupling():
    offenders = _scan(_FORBIDDEN_PI)
    assert not offenders, "Pi/sidecar coupling in kernel/models (SEC-28):\n" + "\n".join(
        offenders
    )
