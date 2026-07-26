from __future__ import annotations

from pathlib import Path

import pytest

from scripts import check_architecture

REPO_ROOT = Path(__file__).resolve().parents[2]


def _layer_root(tmp_path: Path, layer: str) -> Path:
    return tmp_path.joinpath(*check_architecture._LAYER_ROOTS[layer])


def _layer_tree(tmp_path: Path) -> None:
    """Build every declared layer, so adding one cannot silently skip this gate.

    The kernel root is built too: as of 2026-07-26 a MISSING one is a violation
    rather than a silent skip, so a fixture standing in for a repository has to
    have the same parts a repository has. See
    test_a_missing_kernel_root_is_a_violation_not_a_skip.
    """

    for layer in check_architecture._LAYER_IMPORTS:
        root = _layer_root(tmp_path, layer)
        root.mkdir(parents=True, exist_ok=True)
        (root / "__init__.py").write_text("", encoding="utf-8")
    kernel = tmp_path.joinpath(*check_architecture._KERNEL_ROOT)
    kernel.mkdir(parents=True, exist_ok=True)
    (kernel / "__init__.py").write_text("", encoding="utf-8")


def test_a_missing_kernel_root_is_a_violation_not_a_skip(tmp_path: Path) -> None:
    """Relocating boltrig/kernel used to make its whole deny-list evaporate.

    The layer loop emitted a violation for a missing root; four lines below it the
    kernel check was a bare `if kernel_root.is_dir():` with no else. So a rename
    would have stopped `_KERNEL_FORBIDDEN` being enforced at all while the gate
    printed "architecture boundary clean" - a scan that checked nothing, reported
    as nothing wrong.
    """
    _layer_tree(tmp_path)
    import shutil

    shutil.rmtree(tmp_path.joinpath(*check_architecture._KERNEL_ROOT))

    report = check_architecture.check_repository(tmp_path)

    assert [v.path for v in report.violations] == ["boltrig/kernel"]
    assert "checked nothing" in report.violations[0].reason


def test_inward_only_imports_pass(tmp_path: Path) -> None:
    _layer_tree(tmp_path)
    (tmp_path / "boltrig/fleet/domain/model.py").write_text(
        "from dataclasses import dataclass\nfrom boltrig.models import GrantSet\n",
        encoding="utf-8",
    )
    (tmp_path / "boltrig/fleet/ports/runtime.py").write_text(
        "from typing import Protocol\nfrom boltrig.fleet.domain.model import GrantSet\n",
        encoding="utf-8",
    )
    (tmp_path / "boltrig/fleet/application/run.py").write_text(
        "from ..ports.runtime import Protocol\n",
        encoding="utf-8",
    )

    report = check_architecture.check_repository(tmp_path)

    assert report.violations == ()


@pytest.mark.parametrize(
    ("layer", "source", "dependency"),
    [
        ("domain", "from fastapi import FastAPI\n", "fastapi"),
        ("domain", "from ...kernel import Kernel\n", "boltrig.kernel"),
        (
            "ports",
            "from boltrig.fleet.infrastructure import adapter\n",
            "boltrig.fleet.infrastructure",
        ),
        ("application", "from boltrig.store import Store\n", "boltrig.store"),
        # models is the innermost layer: it may not reach back out into fleet,
        # which is what keeps a record from carrying a fleet-owned type.
        (
            "models",
            "from boltrig.fleet.domain.grant_lease import GrantLeaseBinding\n",
            "boltrig.fleet.domain.grant_lease",
        ),
        ("models", "from boltrig.fleet import domain\n", "boltrig.fleet"),
    ],
)
def test_outward_or_framework_dependency_fails(
    tmp_path: Path, layer: str, source: str, dependency: str
) -> None:
    _layer_tree(tmp_path)
    (_layer_root(tmp_path, layer) / "bad.py").write_text(source, encoding="utf-8")

    report = check_architecture.check_repository(tmp_path)

    assert any(item.dependency == dependency for item in report.violations)


@pytest.mark.parametrize(
    "source",
    [
        '__import__("boltrig.kernel")\n',
        'from importlib import import_module as load\nload("boltrig.kernel")\n',
        'import importlib\ngetattr(importlib, "import_module")("boltrig.kernel")\n',
        'eval("__import__(\\"boltrig.kernel\\")")\n',
    ],
)
def test_common_dynamic_import_bypasses_are_rejected(tmp_path: Path, source: str) -> None:
    _layer_tree(tmp_path)
    (tmp_path / "boltrig/fleet/domain/bad.py").write_text(source, encoding="utf-8")

    report = check_architecture.check_repository(tmp_path)

    assert any(item.reason == "dynamic import bypasses gate" for item in report.violations)


@pytest.mark.invariant("FR-ARC-01")
def test_thin_orchestration_layers_depend_inward_only() -> None:
    report = check_architecture.check_repository(REPO_ROOT)

    assert report.violations == (), "\n".join(item.render() for item in report.violations)
