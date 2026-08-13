"""The generated VDS ledgers must stay source-bound in the required gate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scripts import check_vds_ledgers
from scripts.vds_ledger_support import load_yaml, sha256, value_digest

ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = ROOT / "Makefile"
CI = ROOT / ".github/workflows/ci.yml"


def _reference(name: str, line: int, *, component: bool = False) -> dict[str, object]:
    row: dict[str, object] = {
        "name": name,
        "root": name,
        "export_name": name if component else None,
        "namespace_member": False,
        "kind": "component" if component else "element",
        "import_path": "./chat/Composer" if component else None,
        "line": line,
    }
    if component:
        row["resolved_path"] = "ui/chat/Composer"
    return row


def _screen_source(index: int) -> str:
    if index == 0:
        return (
            'import { Composer } from "./chat/Composer";\n'
            "export function Screen0View() {\n"
            "  return <Composer />;\n"
            "}\n"
        )
    return f"export function Screen{index}View() {{ return <div />; }}\n"


def _screen_ledger(root: Path) -> dict[str, object]:
    routes = [f"ui/Screen{index}View.tsx" for index in range(10)]
    rows: list[dict[str, object]] = []
    for index, route in enumerate(routes):
        path = root / route
        rows.append(
            {
                "route": route,
                "digest": sha256(path),
                "references": [
                    _reference("Composer", 3, component=True)
                    if index == 0
                    else _reference("div", 1)
                ],
            }
        )
    source_rows = [[row["route"], row["digest"]] for row in rows]
    ledger: dict[str, object] = {
        "schema_version": 1,
        "generated_at": "2099-01-01T00:00:00Z",
        "generated_by": "vds ledger screens",
        "source_globs": ["ui/*View.tsx"],
        "source_digest": value_digest(source_rows),
        "content_digest": "sha256:" + "0" * 64,
        "screens": rows,
    }
    content = {
        key: value for key, value in ledger.items() if key not in {"generated_at", "content_digest"}
    }
    ledger["content_digest"] = value_digest(content)
    return ledger


def _route_manifest(root: Path) -> dict[str, object]:
    evidence = root / "evidence/current"
    evidence.mkdir(parents=True)
    source_digest = check_vds_ledgers.source_tree_digest(root, ("ui",))
    capture = {
        "status": "captured_unreviewed",
        "visualVerdict": "not_assessed",
        "vdsReviewsUpdated": False,
        "sourceBinding": {
            "status": "current_at_capture",
            "scope": ["ui"],
            "digestAlgorithm": "sha256-path-type-content-v1",
            "digestBeforeCapture": source_digest,
            "digestAfterCapture": source_digest,
            "sourceUnchangedDuringCapture": True,
        },
    }
    (evidence / "capture-manifest.json").write_text(json.dumps(capture) + "\n", encoding="utf-8")
    (evidence / "metrics.json").write_text("{}\n", encoding="utf-8")
    manifest: dict[str, object] = {
        "schemaVersion": 1,
        "generatedBy": "fixture route owner",
        "takenAt": "2099-01-01T00:00:00Z",
        "source": (
            "evidence/current/capture-manifest.json "
            f"({sha256(evidence / 'capture-manifest.json')}) and metrics.json "
            f"({sha256(evidence / 'metrics.json')})"
        ),
        "routes": [f"ui/Screen{index}View.tsx" for index in range(6)],
        "doesNotCover": [
            "There is no non-invented frameDigest for the shared route.",
            "This creates no frameDigest, sign-off or authority.",
            "There is no signed full-frame target.",
        ],
        "contentDigest": "sha256:" + "0" * 64,
    }
    manifest["contentDigest"] = value_digest(
        {key: value for key, value in manifest.items() if key != "contentDigest"}
    )
    return manifest


def _fixture(root: Path) -> str:
    (root / ".vds/ledgers").mkdir(parents=True)
    (root / "ui/chat").mkdir(parents=True)
    (root / "ui/chat/Composer.tsx").write_text(
        "export function Composer() { return <div />; }\n", encoding="utf-8"
    )
    for index in range(10):
        (root / f"ui/Screen{index}View.tsx").write_text(_screen_source(index), encoding="utf-8")
    (root / ".vds/config.toml").write_text(
        """[surface]
screen_globs = ["ui/*View.tsx"]
screens_ledger = ".vds/ledgers/screens.yaml"
component_extensions = ["tsx", "jsx"]

[review]
route_manifest = ".vds/ledgers/routes.yaml"
capture_source_scope = ["ui"]
""",
        encoding="utf-8",
    )
    screens = _screen_ledger(root)
    (root / ".vds/ledgers/screens.yaml").write_text(
        yaml.safe_dump(screens, sort_keys=False), encoding="utf-8"
    )
    routes = _route_manifest(root)
    route_source = "evidence/current/vds-route-manifest.json"
    (root / route_source).write_text(json.dumps(routes, indent=2) + "\n", encoding="utf-8")
    (root / ".vds/ledgers/routes.yaml").write_text(
        yaml.safe_dump(routes, sort_keys=False), encoding="utf-8"
    )
    return route_source


@pytest.mark.invariant("NFR-MNT-08")
def test_repository_vds_ledgers_are_current_and_required_by_quality() -> None:
    report = check_vds_ledgers.check_repository(ROOT)
    assert report.errors == ()
    assert report.screen_count >= check_vds_ledgers.MIN_SCREEN_FILES
    assert report.route_count >= check_vds_ledgers.MIN_ROUTE_FILES

    makefile = MAKEFILE.read_text(encoding="utf-8")
    assert "vds-ledgers: ## Refuse stale VDS" in makefile
    assert "$(PY) scripts/check_vds_ledgers.py" in makefile
    assert "python-quality: invariants lint architecture structure vds-ledgers" in makefile
    assert "run: make python-quality PY=python" in CI.read_text(encoding="utf-8")


@pytest.mark.invariant("NFR-MNT-08")
def test_a_screen_changed_after_generation_is_rejected(tmp_path: Path) -> None:
    route_source = _fixture(tmp_path)
    assert check_vds_ledgers.check_repository(tmp_path, route_source=route_source).errors == ()

    with (tmp_path / "ui/Screen0View.tsx").open("a", encoding="utf-8") as handle:
        handle.write("// extraction moved this screen after ledger generation\n")

    errors = check_vds_ledgers.check_repository(tmp_path, route_source=route_source).errors
    assert "screens ledger source_digest is stale" in errors
    assert "ui/Screen0View.tsx: source digest is stale" in errors


@pytest.mark.invariant("NFR-MNT-08")
def test_an_extracted_import_cannot_remain_recorded_as_local(tmp_path: Path) -> None:
    route_source = _fixture(tmp_path)
    ledger_path = tmp_path / ".vds/ledgers/screens.yaml"
    ledger = load_yaml(ledger_path)
    composer = ledger["screens"][0]["references"][0]
    composer["import_path"] = None
    composer.pop("resolved_path")
    composer["unresolved_because"] = "recorded before Composer was extracted"
    content = {
        key: value for key, value in ledger.items() if key not in {"generated_at", "content_digest"}
    }
    ledger["content_digest"] = value_digest(content)
    ledger_path.write_text(yaml.safe_dump(ledger, sort_keys=False), encoding="utf-8")

    errors = check_vds_ledgers.check_repository(tmp_path, route_source=route_source).errors
    assert any("Composer is recorded local/unresolved" in error for error in errors)


@pytest.mark.invariant("NFR-MNT-08")
def test_route_source_hash_drift_is_rejected_without_visual_authority(tmp_path: Path) -> None:
    route_source = _fixture(tmp_path)
    with (tmp_path / "evidence/current/capture-manifest.json").open(
        "a", encoding="utf-8"
    ) as handle:
        handle.write(" \n")

    errors = check_vds_ledgers.check_repository(tmp_path, route_source=route_source).errors
    assert "route manifest capture digest is stale" in errors


@pytest.mark.invariant("NFR-MNT-08")
def test_worker_source_changed_after_capture_is_rejected(tmp_path: Path) -> None:
    route_source = _fixture(tmp_path)
    assert check_vds_ledgers.check_repository(tmp_path, route_source=route_source).errors == ()

    with (tmp_path / "ui/chat/Composer.tsx").open("a", encoding="utf-8") as handle:
        handle.write("// source moved after the governed capture\n")

    errors = check_vds_ledgers.check_repository(tmp_path, route_source=route_source).errors
    assert any("route capture source digest is stale" in error for error in errors)
