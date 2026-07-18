from __future__ import annotations

import hashlib
import stat
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from boltrig.fleet.infrastructure import skill_config as skill_config_module
from boltrig.fleet.infrastructure.skill_artifacts import (
    ArtifactProjectionError,
    MaterializedSkill,
    SelectedSkillSource,
    digest_directory,
    materialize_selected_skills,
)
from boltrig.fleet.infrastructure.skill_config import (
    CODEX_SKILL_POLICY_VERSION,
    REVIEWED_SYSTEM_SKILLS_0_144_3,
    project_skill_config,
    render_skill_config_fragment,
)


def _skill(catalogue: Path, name: str) -> SelectedSkillSource:
    source = catalogue / name
    source.mkdir(parents=True)
    manifest = f"---\nname: {name}\ndescription: Selected skill\n---\nBody\n".encode()
    (source / "SKILL.md").write_bytes(manifest)
    digest = digest_directory(source)
    return SelectedSkillSource(
        name=name,
        source_path=str(source),
        expected_directory_digest=digest.digest,
        expected_manifest_digest=f"sha256:{hashlib.sha256(manifest).hexdigest()}",
    )


def _layout(
    tmp_path: Path,
    names: tuple[str, ...] = ("legal-review",),
) -> tuple[Path, Path, tuple[MaterializedSkill, ...]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    catalogue = tmp_path / "catalogue"
    catalogue.mkdir()
    selected = tuple(_skill(catalogue, name) for name in names)
    cell = tmp_path / "cell"
    codex_home = cell / "codex"
    codex_home.mkdir(parents=True, mode=0o700)
    materialized = materialize_selected_skills(
        selected,
        catalogue_root=catalogue,
        cell_root=cell,
        codex_home=codex_home,
    )
    return cell, codex_home, materialized


def _entries(config_path: Path) -> list[dict[str, object]]:
    document = tomllib.loads(config_path.read_text(encoding="utf-8"))
    skills = document["skills"]
    assert isinstance(skills, dict)
    entries = skills["config"]
    assert isinstance(entries, list)
    return entries


def test_projects_exact_reviewed_system_disables_and_selected_enables(tmp_path: Path) -> None:
    cell, codex_home, selected = _layout(tmp_path, ("writing", "legal-review"))

    receipt = project_skill_config(
        tuple(reversed(selected)),
        cell_root=cell,
        codex_home=codex_home,
    )

    config_path = Path(receipt.config_path)
    entries = _entries(config_path)
    assert receipt.codex_version == "0.144.3"
    assert receipt.enabled_selected_names == ("legal-review", "writing")
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o400
    assert set().union(*(entry.keys() for entry in entries)) == {"path", "enabled"}
    assert [entry["enabled"] for entry in entries[:5]] == [False] * 5
    assert [entry["enabled"] for entry in entries[5:]] == [True, True]
    expected_digest = "sha256:" + hashlib.sha256(config_path.read_bytes()).hexdigest()
    assert receipt.config_digest == expected_digest


def test_reviewed_builtin_paths_are_exact_and_under_system_root(tmp_path: Path) -> None:
    cell, codex_home, selected = _layout(tmp_path, ())

    receipt = project_skill_config(selected, cell_root=cell, codex_home=codex_home)

    assert CODEX_SKILL_POLICY_VERSION == "0.144.3"
    assert REVIEWED_SYSTEM_SKILLS_0_144_3 == (
        "imagegen",
        "openai-docs",
        "plugin-creator",
        "skill-creator",
        "skill-installer",
    )
    paths = [entry["path"] for entry in _entries(Path(receipt.config_path))]
    assert paths == [
        str(codex_home / "skills" / ".system" / name / "SKILL.md")
        for name in REVIEWED_SYSTEM_SKILLS_0_144_3
    ]


def test_config_documents_attestation_as_authoritative_defense(tmp_path: Path) -> None:
    cell, codex_home, selected = _layout(tmp_path)

    receipt = project_skill_config(selected, cell_root=cell, codex_home=codex_home)
    text = Path(receipt.config_path).read_text(encoding="utf-8")

    assert "defense in depth" in text
    assert "force-reloaded exact enabled-set attestation remains authoritative" in text


def test_validated_fragment_is_deterministic_and_composable(tmp_path: Path) -> None:
    cell, codex_home, selected = _layout(tmp_path, ("writing", "legal-review"))

    first = render_skill_config_fragment(
        tuple(reversed(selected)), cell_root=cell, codex_home=codex_home
    )
    second = render_skill_config_fragment(
        selected, cell_root=cell, codex_home=codex_home
    )

    assert first == second
    document = tomllib.loads(
        (first + b'\n[mcp_servers.opbox]\ncommand = "/bin/false"\n').decode("utf-8")
    )
    assert document["mcp_servers"] == {"opbox": {"command": "/bin/false"}}
    assert len(document["skills"]["config"]) == 7


def test_existing_config_is_never_overwritten(tmp_path: Path) -> None:
    cell, codex_home, selected = _layout(tmp_path)
    config_path = codex_home / "config.toml"
    config_path.write_text("existing = true\n", encoding="utf-8")

    with pytest.raises(ArtifactProjectionError, match="exclusively"):
        project_skill_config(selected, cell_root=cell, codex_home=codex_home)

    assert config_path.read_text(encoding="utf-8") == "existing = true\n"


def test_existing_config_symlink_is_never_followed(tmp_path: Path) -> None:
    cell, codex_home, selected = _layout(tmp_path)
    target = tmp_path / "outside.toml"
    target.write_text("outside = true\n", encoding="utf-8")
    (codex_home / "config.toml").symlink_to(target)

    with pytest.raises(ArtifactProjectionError, match="exclusively"):
        project_skill_config(selected, cell_root=cell, codex_home=codex_home)

    assert target.read_text(encoding="utf-8") == "outside = true\n"


def test_projection_detects_replacement_and_never_unlinks_foreign_inode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cell, codex_home, selected = _layout(tmp_path)
    config_path = codex_home / "config.toml"
    displaced = codex_home / "displaced.toml"
    original_write = skill_config_module._write_all

    def replace_after_write(descriptor: int, contents: bytes) -> None:
        original_write(descriptor, contents)
        config_path.rename(displaced)
        config_path.write_text("foreign = true\n", encoding="utf-8")

    monkeypatch.setattr(skill_config_module, "_write_all", replace_after_write)

    with pytest.raises(ArtifactProjectionError, match="exclusively"):
        project_skill_config(selected, cell_root=cell, codex_home=codex_home)

    assert config_path.read_text(encoding="utf-8") == "foreign = true\n"
    assert displaced.is_file()


def test_selected_artifact_digest_is_rechecked_before_enabling(tmp_path: Path) -> None:
    cell, codex_home, selected = _layout(tmp_path)
    manifest = Path(selected[0].manifest_path)
    manifest.parent.chmod(0o700)
    manifest.chmod(0o600)
    manifest.write_text("---\nname: legal-review\n---\nChanged\n", encoding="utf-8")
    manifest.chmod(0o400)
    manifest.parent.chmod(0o500)

    with pytest.raises(ArtifactProjectionError, match="changed"):
        project_skill_config(selected, cell_root=cell, codex_home=codex_home)

    assert not (codex_home / "config.toml").exists()


def test_selected_path_cannot_escape_the_isolated_skill_root(tmp_path: Path) -> None:
    cell, codex_home, selected = _layout(tmp_path)
    forged = replace(selected[0], manifest_path=str(tmp_path / "outside" / "SKILL.md"))

    with pytest.raises(ArtifactProjectionError, match="outside"):
        project_skill_config((forged,), cell_root=cell, codex_home=codex_home)


def test_selected_names_cannot_duplicate_or_shadow_system_skills(tmp_path: Path) -> None:
    cell, codex_home, selected = _layout(tmp_path)
    with pytest.raises(ArtifactProjectionError, match="unique"):
        project_skill_config(selected * 2, cell_root=cell, codex_home=codex_home)

    other = tmp_path / "other"
    other_cell, other_home, system_named = _layout(other, ("imagegen",))
    with pytest.raises(ArtifactProjectionError, match="non-system"):
        project_skill_config(system_named, cell_root=other_cell, codex_home=other_home)


@pytest.mark.parametrize("control", ["\n", "\x85"])
def test_control_characters_in_derived_paths_are_rejected(
    tmp_path: Path,
    control: str,
) -> None:
    cell = tmp_path / "cell"
    codex_home = cell / f"co{control}dex"
    codex_home.mkdir(parents=True, mode=0o700)
    catalogue = tmp_path / "catalogue"
    catalogue.mkdir()
    selected = materialize_selected_skills(
        (), catalogue_root=catalogue, cell_root=cell, codex_home=codex_home
    )

    with pytest.raises(ArtifactProjectionError, match="control"):
        project_skill_config(selected, cell_root=cell, codex_home=codex_home)

    assert not (codex_home / "config.toml").exists()


def test_codex_home_must_be_private_exact_child_with_locked_skills(tmp_path: Path) -> None:
    cell, codex_home, selected = _layout(tmp_path)
    (codex_home / "skills").chmod(0o700)
    with pytest.raises(ArtifactProjectionError, match="locked"):
        project_skill_config(selected, cell_root=cell, codex_home=codex_home)

    nested_parent = tmp_path / "nested-cell"
    nested_home = nested_parent / "nested" / "codex"
    nested_home.mkdir(parents=True, mode=0o700)
    catalogue = tmp_path / "empty-catalogue"
    catalogue.mkdir()
    materialize_selected_skills(
        (),
        catalogue_root=catalogue,
        cell_root=nested_home.parent,
        codex_home=nested_home,
    )
    with pytest.raises(ArtifactProjectionError, match="exact child"):
        project_skill_config((), cell_root=nested_parent, codex_home=nested_home)
