"""Bounded filesystem projection for isolated Codex workspaces and skills."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from boltrig.fleet.domain.skill_attestation import (
    ExpectedSkill,
    SkillScope,
    absolute_posix_path,
    sha256_digest,
    skill_name,
)
from .bounded_filesystem import (
    ArtifactProjectionError,
    CONTROL_NAMES,
    DirectoryCapture,
    DirectoryDigest,
    FilesystemLimits,
    canonical_existing_directory,
    capture_directory,
    digest_directory,
    exact_destination,
    paths_overlap,
    write_capture,
)


@dataclass(frozen=True)
class SanitizedWorkspaceProjection:
    """Read-only workspace snapshot with all Codex and VCS control layers removed."""

    source_path: str
    workspace_path: str
    workspace_digest: str
    file_count: int
    total_bytes: int

    def __post_init__(self) -> None:
        absolute_posix_path(self.source_path)
        absolute_posix_path(self.workspace_path)
        sha256_digest(self.workspace_digest)
        if type(self.file_count) is not int or self.file_count < 0:
            raise ValueError("workspace file count must be a non-negative integer")
        if type(self.total_bytes) is not int or self.total_bytes < 0:
            raise ValueError("workspace byte count must be a non-negative integer")


@dataclass(frozen=True, order=True)
class SelectedSkillSource:
    """One immutable catalogue artifact selected by exact expected digests."""

    name: str
    source_path: str
    expected_directory_digest: str
    expected_manifest_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", skill_name(self.name))
        object.__setattr__(self, "source_path", absolute_posix_path(self.source_path))
        sha256_digest(self.expected_directory_digest)
        sha256_digest(self.expected_manifest_digest)


@dataclass(frozen=True, order=True)
class MaterializedSkill:
    """A selected skill copied into the only enabled user-skill root."""

    name: str
    manifest_path: str
    directory_digest: str
    manifest_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", skill_name(self.name))
        object.__setattr__(self, "manifest_path", absolute_posix_path(self.manifest_path))
        sha256_digest(self.directory_digest)
        sha256_digest(self.manifest_digest)
        if not self.manifest_path.endswith("/SKILL.md"):
            raise ValueError("materialized skill path must end in SKILL.md")

    def expected(self) -> ExpectedSkill:
        return ExpectedSkill(
            name=self.name,
            manifest_path=self.manifest_path,
            scope=SkillScope.USER,
            directory_digest=self.directory_digest,
            manifest_digest=self.manifest_digest,
        )


def _remove_tree(path: Path) -> None:
    """Make our own read-only capture removable, then erase it without following links."""

    try:
        for root, _directories, _files in os.walk(path, topdown=True, followlinks=False):
            os.chmod(root, 0o700, follow_symlinks=False)
    except OSError:
        pass
    shutil.rmtree(path, ignore_errors=True)


def _install_capture(capture: DirectoryCapture, cell_root: Path, destination: Path) -> None:
    stage = Path(tempfile.mkdtemp(prefix=".projection-", dir=cell_root))
    try:
        write_capture(capture, stage)
        os.rename(stage, destination)
    except BaseException:
        _remove_tree(stage)
        raise


def project_sanitized_workspace(
    source_root: Path,
    *,
    cell_root: Path,
    destination: Path,
    limits: FilesystemLimits = FilesystemLimits(),
) -> SanitizedWorkspaceProjection:
    """Capture a read-only workspace while excluding every nested control layer."""

    root, target = exact_destination(cell_root, destination)
    source = canonical_existing_directory(source_root, "workspace source")
    if paths_overlap(source, root):
        raise ArtifactProjectionError("workspace source and cell root must not overlap")
    capture = capture_directory(source, limits, reject_controls=False)
    _install_capture(capture, root, target)
    return SanitizedWorkspaceProjection(
        source_path=str(source),
        workspace_path=str(target),
        workspace_digest=capture.accounting.digest,
        file_count=capture.accounting.file_count,
        total_bytes=capture.accounting.total_bytes,
    )


def _manifest_name(contents: bytes) -> str:
    if len(contents) > 64 * 1024:
        raise ArtifactProjectionError("skill manifest exceeds its bounded size")
    try:
        lines = contents.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise ArtifactProjectionError("skill manifest must be UTF-8") from exc
    if not lines or lines[0] != "---":
        raise ArtifactProjectionError("skill manifest requires bounded front matter")
    names: list[str] = []
    for line in lines[1:101]:
        if line == "---":
            break
        key, separator, value = line.partition(":")
        if separator and key.strip() == "name":
            names.append(value.strip())
    else:
        raise ArtifactProjectionError("skill manifest front matter is not bounded")
    if len(names) != 1:
        raise ArtifactProjectionError("skill manifest requires exactly one name")
    try:
        return skill_name(names[0])
    except ValueError as exc:
        raise ArtifactProjectionError("skill manifest name is invalid") from exc


def _validated_skill_capture(
    source: SelectedSkillSource,
    catalogue_root: Path,
    limits: FilesystemLimits,
) -> tuple[DirectoryCapture, str]:
    path = canonical_existing_directory(Path(source.source_path), "skill source")
    if path == catalogue_root or catalogue_root not in path.parents:
        raise ArtifactProjectionError("skill source escapes the allowed catalogue root")
    if any(component in CONTROL_NAMES for component in path.relative_to(catalogue_root).parts):
        raise ArtifactProjectionError("skill source uses a forbidden control path")
    capture = capture_directory(path, limits, reject_controls=True)
    manifest = capture.file("SKILL.md")
    manifest_digest = f"sha256:{manifest.content_digest}"
    if _manifest_name(manifest.contents) != source.name:
        raise ArtifactProjectionError("skill manifest name does not match its selection")
    if (
        capture.accounting.digest != source.expected_directory_digest
        or manifest_digest != source.expected_manifest_digest
    ):
        raise ArtifactProjectionError("selected skill artifact digest does not match")
    return capture, manifest_digest


def materialize_selected_skills(
    selected: tuple[SelectedSkillSource, ...],
    *,
    catalogue_root: Path,
    cell_root: Path,
    codex_home: Path,
    limits: FilesystemLimits = FilesystemLimits(),
) -> tuple[MaterializedSkill, ...]:
    """Install only digest-pinned selections into a new isolated user-skill root."""

    if len(selected) > 128 or any(not isinstance(item, SelectedSkillSource) for item in selected):
        raise ArtifactProjectionError("selected skill set is invalid or unbounded")
    names = [item.name for item in selected]
    paths = [item.source_path for item in selected]
    if len(names) != len(set(names)) or len(paths) != len(set(paths)):
        raise ArtifactProjectionError("selected skill names and sources must be unique")
    cell = canonical_existing_directory(cell_root, "cell root")
    home = canonical_existing_directory(codex_home, "Codex home")
    catalogue = canonical_existing_directory(catalogue_root, "skill catalogue root")
    if home.parent != cell or paths_overlap(catalogue, cell):
        raise ArtifactProjectionError("skill catalogue and isolated cell layout are unsafe")
    skills_root = home / "skills"
    if skills_root.exists() or skills_root.is_symlink():
        raise ArtifactProjectionError("isolated Codex home already contains a skills root")
    captures = [(item, *_validated_skill_capture(item, catalogue, limits)) for item in selected]
    skills_root.mkdir(mode=0o700)
    results: list[MaterializedSkill] = []
    try:
        for item, capture, manifest_digest in sorted(captures, key=lambda value: value[0].name):
            target = skills_root / item.name
            target.mkdir(mode=0o700)
            write_capture(capture, target)
            results.append(
                MaterializedSkill(
                    name=item.name,
                    manifest_path=str(target / "SKILL.md"),
                    directory_digest=capture.accounting.digest,
                    manifest_digest=manifest_digest,
                )
            )
        skills_root.chmod(0o500)
    except BaseException:
        _remove_tree(skills_root)
        raise
    return tuple(results)


__all__ = [
    "ArtifactProjectionError",
    "CONTROL_NAMES",
    "DirectoryDigest",
    "FilesystemLimits",
    "MaterializedSkill",
    "SanitizedWorkspaceProjection",
    "SelectedSkillSource",
    "digest_directory",
    "materialize_selected_skills",
    "project_sanitized_workspace",
]
