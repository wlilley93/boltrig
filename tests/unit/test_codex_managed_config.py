"""The root-owned managed Codex config must stay in step with the code.

[2026] VJS-CC-VJS 6 H5 ordered the cell-invariant security-critical keys pinned in
``/etc/codex/managed_config.toml`` as well as in the per-cell file, because the
managed layer sits on the read-only image mount and BEATS a hostile
``$CODEX_HOME/config.toml`` that a sibling cell rewrote.

Two files now assert the same policy, which is exactly the drift risk the "derive
from the record" ratio warns about. The managed file cannot be derived at runtime
(it is baked into the image at build time), so it is held in step by this test
instead: if someone disables a new feature in the code and forgets the image, the
gate says so rather than a cell silently running with it enabled.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from boltrig.fleet.infrastructure.codex_runtime_config_toml import (
    CODEX_RUNTIME_DISABLED_FEATURES,
)

_MANAGED = Path(__file__).resolve().parents[2] / "deploy" / "codex" / "managed_config.toml"


def _document() -> dict[str, object]:
    return tomllib.loads(_MANAGED.read_text(encoding="utf-8"))


@pytest.mark.unit
def test_the_managed_config_disables_exactly_the_features_the_code_disables() -> None:
    features = _document()["features"]
    assert isinstance(features, dict)
    assert features == dict(CODEX_RUNTIME_DISABLED_FEATURES)


@pytest.mark.unit
def test_the_managed_config_pins_the_sandbox_and_approval_posture() -> None:
    document = _document()
    assert document["sandbox_mode"] == "read-only"
    assert document["approval_policy"] == "never"
    assert document["web_search"] == "disabled"


@pytest.mark.unit
def test_the_managed_config_carries_no_per_cell_value() -> None:
    """Per-cell values belong on argv, not in a file shared by every cell.

    A provider table here would name ONE cell's loopback port and ONE cell's
    ingress socket, and every other cell would then be pointed at it.
    """

    document = _document()
    assert "model_providers" not in document
    assert "model_provider" not in document
    for key in ("auth", "base_url", "cell_id"):
        assert key not in document


@pytest.mark.unit
def test_the_managed_config_is_installed_root_owned_and_read_only_in_both_images() -> None:
    """The whole boundary is that no cell can write it, so the image must say so."""

    root = Path(__file__).resolve().parents[2] / "deploy"
    for dockerfile in ("kernel.Dockerfile", "fleet.Dockerfile"):
        text = (root / dockerfile).read_text(encoding="utf-8")
        assert "COPY deploy/codex/managed_config.toml /etc/codex/managed_config.toml" in text
        assert "chown 0:0 /etc/codex/managed_config.toml" in text
        assert "chmod 0444 /etc/codex/managed_config.toml" in text
