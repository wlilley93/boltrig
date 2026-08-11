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

_REPO = pathlib.Path(__file__).resolve().parents[2]
_ROOT = _REPO / "boltrig"
_CHANNEL_GATEWAY = _REPO / "services" / "channel_gateway"
_SCOPED = [_ROOT / "kernel", _ROOT / "models"]

# import tokens that would indicate coupling to a sibling estate kernel
_FORBIDDEN = re.compile(
    r"^\s*(?:from|import)\s+(hermes|phoenix|opbox|agent_libos|agentlibos|vjs)\b",
    re.IGNORECASE,
)

# Round Two: the kernel/models must not import Pi or the gateway; the gateway is
# reached over the wire only (SEC-28). Also forbid runtime-backbone specifics
# (hatchet, the fleet's pi_runtime) leaking into the core. Decision 0003 (Phase
# 2, condition 3): the channel gateway joins the same forbidden set.
_FORBIDDEN_PI = re.compile(
    r"^\s*(?:from|import)\s+(.*\b)?(pi_runtime|pi_sidecar|channel_gateway|hatchet|hatchet_sdk)\b",
    re.IGNORECASE,
)


def _python_files() -> list[pathlib.Path]:
    """Every scoped source file, with a FLOOR.

    An empty glob yields no offenders, so this test would pass having read
    nothing - and "no estate-coupling imports" would be true the way it is true
    of an empty directory. One rename of boltrig/kernel is all it takes. Each
    scope must exist and must contain something.
    """
    files: list[pathlib.Path] = []
    for scope in _SCOPED:
        assert scope.is_dir(), f"scanned nothing: {scope} does not exist"
        found = list(scope.rglob("*.py"))
        assert found, f"scanned nothing: {scope} holds no Python"
        files.extend(found)
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
    assert not offenders, "Pi/gateway coupling in kernel/models (SEC-28):\n" + "\n".join(
        offenders
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-28")
def test_channel_gateway_imports_no_boltrig_package_code():
    # Decision 0003, condition 3: the channel gateway is severed exactly like
    # the retired pi_sidecar was - the only coupling is the wire protocol (signed intake
    # POSTs + the run-scoped outbox links), never a package import.
    offenders: list[str] = []
    pattern = re.compile(r"^\s*(?:from|import)\s+boltrig(?:\.|\b)")
    # The same "scanned nothing" floor the other sweeps in this file carry, and
    # for the same reason: the only assertion here is that a list is EMPTY, so a
    # gateway that moved, was renamed, or lost its sources would satisfy it
    # forever without a line being read.
    gateway_sources = sorted(_CHANNEL_GATEWAY.rglob("*.py"))
    assert len(gateway_sources) >= 5, (
        f"scanned nothing: {_CHANNEL_GATEWAY} yielded {len(gateway_sources)} "
        "Python file(s), and the severance check below is negative-only"
    )
    for path in gateway_sources:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.match(line):
                offenders.append(f"{path}:{n}: {line.strip()}")
    assert not offenders, (
        "Channel gateway must stay package-severed and communicate over the "
        "kernel links only (SEC-28, decision 0003):\n" + "\n".join(offenders)
    )


# --- The stack layer-dependency rule (Round Nine, ARCHITECTURE-stack.md) -------
# Boltrig is a stack: foundation (models) -> data (store) / capability (adapters)
# -> kernel -> runtime (fleet) -> API/Worker. The foundation layers must never depend
# UPWARD on the kernel or the runtime, so the seam a future repo-split would cleave
# along stays clean. The kernel is the integration layer and may pull lower layers;
# this rule pins only the lower layers (SEC-54).
_LAYER_RULES = {
    # layer dir -> the boltrig subpackages it must NOT import
    "models": ("kernel", "fleet", "api", "store", "adapters", "workflows",
               "memory", "identity", "observability", "config", "skills", "work",
               "emotion"),
    "store": ("kernel", "fleet", "api", "adapters", "workflows", "memory",
              "identity", "observability", "config", "skills", "work", "emotion"),
    "adapters": ("kernel", "fleet", "api", "store", "workflows", "memory",
                 "identity", "observability", "config", "skills", "work", "emotion"),
    # the emotion add-on is a leaf, fail-safe side-channel (EMO-1): it may see
    # the kernel's relay type and the models, never the runtime, the store,
    # the api, or observability.
    "emotion": ("fleet", "api", "store", "adapters", "observability"),
}


@pytest.mark.security
@pytest.mark.invariant("SEC-54")
def test_foundation_layers_do_not_depend_upward():
    offenders: list[str] = []
    for layer, forbidden in _LAYER_RULES.items():
        pattern = re.compile(
            r"^\s*(?:from|import)\s+boltrig\.(" + "|".join(forbidden) + r")\b"
        )
        # _LAYER_RULES is keyed by directory NAME, so a renamed layer silently
        # drops its own rule and this loop reads zero files for it - a boundary
        # that stops being enforced without anything going red.
        layer_root = _ROOT / layer
        assert layer_root.is_dir(), f"scanned nothing: layer {layer} does not exist"
        paths = list(layer_root.rglob("*.py"))
        assert paths, f"scanned nothing: layer {layer} holds no Python"
        for path in paths:
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.match(line):
                    offenders.append(f"{path}:{n}: {line.strip()}")
    assert not offenders, (
        "stack boundary breach - a foundation layer depends upward (SEC-54):\n"
        + "\n".join(offenders)
    )
