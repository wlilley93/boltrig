from __future__ import annotations

from pathlib import Path

import pytest

from boltrig.fleet.infrastructure import codex_binary_pin


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.invariant("SEC-159")
def test_release_images_install_every_runtime_reviewed_codex_artifact() -> None:
    """Image downloads and runtime admission share exact architecture pins."""

    expected = (
        f"ARG CODEX_VERSION={codex_binary_pin.CODEX_CLI_VERSION}",
        f"ARG CODEX_SHA256={codex_binary_pin.CODEX_CLI_SHA256}",
        f"ARG CODEX_SHA256_ARM64={codex_binary_pin.CODEX_CLI_SHA256_ARM64}",
        f'amd64) triple="{codex_binary_pin.CODEX_CLI_TARGET}"',
        f'arm64) triple="{codex_binary_pin.CODEX_CLI_TARGET_ARM64}"',
    )
    for relative in ("deploy/kernel.Dockerfile", "deploy/fleet.Dockerfile"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        for declaration in expected:
            assert declaration in source, f"{relative} drifted from {declaration}"
