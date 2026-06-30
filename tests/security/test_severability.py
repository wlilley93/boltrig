"""Severability: the kernel and models import nothing from sibling estate kernels.

Machine-enforces directive D5 of [2026] VJS-CC NANKLE-CONSOLIDATION 001: Boltrig
stays a clean, deletable boundary with zero code coupling to Hermes / Phoenix /
Opbox / Agent-libOS / VJS. This turns the "quarterly severability audit" into a
build-red check rather than a manual ritual.
"""

from __future__ import annotations

import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2] / "boltrig"
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


# --- The stack layer-dependency rule (Round Nine, ARCHITECTURE-stack.md) -------
# Boltrig is a stack: foundation (models) -> data (store) / capability (adapters)
# -> kernel -> runtime (fleet) -> api/ui. The foundation layers must never depend
# UPWARD on the kernel or the runtime, so the seam a future repo-split would cleave
# along stays clean. The kernel is the integration layer and may pull lower layers;
# this rule pins only the lower layers (SEC-54).
_LAYER_RULES = {
    # layer dir -> the boltrig subpackages it must NOT import
    "models": ("kernel", "fleet", "api", "store", "adapters", "workflows",
               "memory", "identity", "observability", "config", "skills", "work"),
    "store": ("kernel", "fleet", "api", "adapters", "workflows", "memory",
              "identity", "observability", "config", "skills", "work"),
    "adapters": ("kernel", "fleet", "api", "store", "workflows", "memory",
                 "identity", "observability", "config", "skills", "work"),
}


@pytest.mark.security
@pytest.mark.invariant("SEC-54")
def test_foundation_layers_do_not_depend_upward():
    offenders: list[str] = []
    for layer, forbidden in _LAYER_RULES.items():
        pattern = re.compile(
            r"^\s*(?:from|import)\s+boltrig\.(" + "|".join(forbidden) + r")\b"
        )
        for path in (_ROOT / layer).rglob("*.py"):
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.match(line):
                    offenders.append(f"{path}:{n}: {line.strip()}")
    assert not offenders, (
        "stack boundary breach - a foundation layer depends upward (SEC-54):\n"
        + "\n".join(offenders)
    )
