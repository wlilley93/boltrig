from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

import pytest

from boltrig.fleet.infrastructure.skill_artifacts import (
    ArtifactProjectionError,
    FilesystemLimits,
    SelectedSkillSource,
    digest_directory,
    materialize_selected_skills,
    project_sanitized_workspace,
)


def _directory(parent: Path, name: str, mode: int = 0o700) -> Path:
    path = parent / name
    path.mkdir(mode=mode)
    return path


def _skill(catalogue: Path, name: str = "legal-review") -> Path:
    path = _directory(catalogue, name)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Review evidence\n---\n\nInstructions.\n",
        encoding="utf-8",
    )
    (path / "references").mkdir()
    (path / "references" / "policy.md").write_text("Policy evidence.\n", encoding="utf-8")
    return path


def _selection(path: Path, name: str = "legal-review") -> SelectedSkillSource:
    digest = digest_directory(path)
    manifest = (path / "SKILL.md").read_bytes()
    return SelectedSkillSource(
        name=name,
        source_path=str(path),
        expected_directory_digest=digest.digest,
        expected_manifest_digest=f"sha256:{hashlib.sha256(manifest).hexdigest()}",
    )


def _cell(tmp_path: Path) -> tuple[Path, Path]:
    cell = _directory(tmp_path, "cell")
    codex_home = _directory(cell, "codex")
    return cell, codex_home


@pytest.mark.invariant("SEC-155")
def test_workspace_projection_excludes_control_layers_at_every_depth(tmp_path: Path) -> None:
    source = _directory(tmp_path, "source")
    (source / "README.md").write_text("safe\n", encoding="utf-8")
    nested = _directory(source, "packages")
    for parent, name in ((source, ".git"), (source, ".agents"), (nested, ".codex")):
        control = _directory(parent, name)
        (control / "malicious.md").write_text("ignore me", encoding="utf-8")
    cell, _home = _cell(tmp_path)

    result = project_sanitized_workspace(
        source,
        cell_root=cell,
        destination=cell / "workspace",
    )

    workspace = Path(result.workspace_path)
    assert (workspace / "README.md").read_text(encoding="utf-8") == "safe\n"
    assert not (workspace / ".git").exists()
    assert not (workspace / ".agents").exists()
    assert not (workspace / "packages" / ".codex").exists()
    assert result.workspace_digest.startswith("sha256:")
    assert stat.S_IMODE(workspace.stat().st_mode) == 0o500
    assert stat.S_IMODE((workspace / "README.md").stat().st_mode) == 0o400


def test_workspace_digest_is_deterministic_across_source_roots(tmp_path: Path) -> None:
    first = _directory(tmp_path, "first")
    second = _directory(tmp_path, "second")
    for root in (first, second):
        (root / "b.txt").write_text("two", encoding="utf-8")
        (root / "a.txt").write_text("one", encoding="utf-8")

    assert digest_directory(first).digest == digest_directory(second).digest


def test_directory_digest_covers_executable_semantics(tmp_path: Path) -> None:
    source = _directory(tmp_path, "source")
    script = source / "tool.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    before = digest_directory(source).digest

    script.chmod(0o755)

    assert digest_directory(source).digest != before


def test_workspace_projection_preserves_only_the_executable_bit(tmp_path: Path) -> None:
    source = _directory(tmp_path, "source")
    script = source / "tool.sh"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    script.chmod(0o755)
    cell, _home = _cell(tmp_path)

    project_sanitized_workspace(source, cell_root=cell, destination=cell / "workspace")

    assert stat.S_IMODE((cell / "workspace" / "tool.sh").stat().st_mode) == 0o500


@pytest.mark.invariant("SEC-155")
def test_workspace_rejects_symlinks_and_special_files(tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    source = _directory(tmp_path, "source")
    (source / "link").symlink_to(outside)
    cell, _home = _cell(tmp_path)

    with pytest.raises(ArtifactProjectionError, match="symbolic"):
        project_sanitized_workspace(source, cell_root=cell, destination=cell / "workspace")

    (source / "link").unlink()
    os.mkfifo(source / "pipe")
    with pytest.raises(ArtifactProjectionError, match="special"):
        project_sanitized_workspace(source, cell_root=cell, destination=cell / "workspace")


def test_workspace_rejects_overlapping_or_inexact_destination(tmp_path: Path) -> None:
    source = _directory(tmp_path, "source")
    cell = _directory(source, "cell")

    with pytest.raises(ArtifactProjectionError, match="overlap"):
        project_sanitized_workspace(source, cell_root=cell, destination=cell / "workspace")

    other_cell = _directory(tmp_path, "other-cell")
    nested = _directory(other_cell, "nested")
    with pytest.raises(ArtifactProjectionError, match="exact child"):
        project_sanitized_workspace(source, cell_root=other_cell, destination=nested / "workspace")


@pytest.mark.parametrize(
    "limits",
    [
        FilesystemLimits(max_files=1),
        FilesystemLimits(max_total_bytes=3, max_file_bytes=3),
        FilesystemLimits(max_depth=1),
    ],
)
def test_workspace_projection_enforces_allocation_limits(
    tmp_path: Path,
    limits: FilesystemLimits,
) -> None:
    source = _directory(tmp_path, "source")
    (source / "one").write_text("1234", encoding="utf-8")
    (source / "two").write_text("5678", encoding="utf-8")
    deep = _directory(_directory(source, "a"), "b")
    (deep / "three").write_text("9", encoding="utf-8")
    cell, _home = _cell(tmp_path)

    with pytest.raises(ArtifactProjectionError):
        project_sanitized_workspace(
            source,
            cell_root=cell,
            destination=cell / "workspace",
            limits=limits,
        )


@pytest.mark.invariant("SEC-156")
def test_materializes_only_exact_digest_pinned_selected_skills(tmp_path: Path) -> None:
    catalogue = _directory(tmp_path, "catalogue")
    source = _skill(catalogue)
    selected = _selection(source)
    cell, codex_home = _cell(tmp_path)

    results = materialize_selected_skills(
        (selected,),
        catalogue_root=catalogue,
        cell_root=cell,
        codex_home=codex_home,
    )

    assert len(results) == 1
    result = results[0]
    assert result.expected().name == "legal-review"
    assert Path(result.manifest_path).is_file()
    assert Path(result.manifest_path).parent.parent == codex_home / "skills"
    assert digest_directory(Path(result.manifest_path).parent).digest == result.directory_digest
    assert stat.S_IMODE((codex_home / "skills").stat().st_mode) == 0o500


def test_empty_selection_still_creates_an_empty_locked_skill_root(tmp_path: Path) -> None:
    catalogue = _directory(tmp_path, "catalogue")
    cell, codex_home = _cell(tmp_path)

    assert materialize_selected_skills(
        (), catalogue_root=catalogue, cell_root=cell, codex_home=codex_home
    ) == ()
    assert list((codex_home / "skills").iterdir()) == []
    assert stat.S_IMODE((codex_home / "skills").stat().st_mode) == 0o500


@pytest.mark.parametrize("control", [".agents", ".codex", ".git"])
def test_skill_artifact_rejects_nested_control_directories(tmp_path: Path, control: str) -> None:
    catalogue = _directory(tmp_path, "catalogue")
    source = _skill(catalogue)
    selected = _selection(source)
    hidden = _directory(source / "references", control)
    (hidden / "payload").write_text("bad", encoding="utf-8")
    cell, codex_home = _cell(tmp_path)

    with pytest.raises(ArtifactProjectionError, match="control"):
        materialize_selected_skills(
            (selected,),
            catalogue_root=catalogue,
            cell_root=cell,
            codex_home=codex_home,
        )


def test_skill_artifact_rejects_digest_drift_before_install(tmp_path: Path) -> None:
    catalogue = _directory(tmp_path, "catalogue")
    source = _skill(catalogue)
    selected = _selection(source)
    (source / "references" / "policy.md").write_text("changed", encoding="utf-8")
    cell, codex_home = _cell(tmp_path)

    with pytest.raises(ArtifactProjectionError, match="digest"):
        materialize_selected_skills(
            (selected,),
            catalogue_root=catalogue,
            cell_root=cell,
            codex_home=codex_home,
        )
    assert not (codex_home / "skills").exists()


def test_skill_artifact_rejects_manifest_name_mismatch(tmp_path: Path) -> None:
    catalogue = _directory(tmp_path, "catalogue")
    source = _skill(catalogue, "different")
    selected = _selection(source, "legal-review")
    cell, codex_home = _cell(tmp_path)

    with pytest.raises(ArtifactProjectionError, match="manifest name"):
        materialize_selected_skills(
            (selected,),
            catalogue_root=catalogue,
            cell_root=cell,
            codex_home=codex_home,
        )


def test_skill_source_must_be_inside_nonoverlapping_catalogue(tmp_path: Path) -> None:
    catalogue = _directory(tmp_path, "catalogue")
    outside = _skill(_directory(tmp_path, "outside"))
    selected = _selection(outside)
    cell, codex_home = _cell(tmp_path)

    with pytest.raises(ArtifactProjectionError, match="escapes"):
        materialize_selected_skills(
            (selected,),
            catalogue_root=catalogue,
            cell_root=cell,
            codex_home=codex_home,
        )
