"""Deterministic defense-in-depth skill config for the pinned Codex cell."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from boltrig.fleet.domain.skill_attestation import absolute_posix_path, sha256_digest

from .bounded_filesystem import (
    ArtifactProjectionError,
    FilesystemLimits,
    canonical_existing_directory,
    capture_directory,
)
from .skill_artifacts import MaterializedSkill

CODEX_SKILL_POLICY_VERSION = "0.144.3"
REVIEWED_SYSTEM_SKILLS_0_144_3 = (
    "imagegen",
    "openai-docs",
    "plugin-creator",
    "skill-creator",
    "skill-installer",
)
MAX_SKILL_CONFIG_BYTES = 512 * 1024


@dataclass(frozen=True)
class SkillConfigProjection:
    """Audit-safe receipt for one exclusive Codex skill config projection."""

    config_path: str
    config_digest: str
    codex_version: str
    disabled_system_names: tuple[str, ...]
    enabled_selected_names: tuple[str, ...]

    def __post_init__(self) -> None:
        absolute_posix_path(self.config_path)
        sha256_digest(self.config_digest)
        if self.codex_version != CODEX_SKILL_POLICY_VERSION:
            raise ValueError("skill config uses an unsupported Codex version")
        if self.disabled_system_names != REVIEWED_SYSTEM_SKILLS_0_144_3:
            raise ValueError("skill config does not cover the reviewed system skills")
        if tuple(sorted(set(self.enabled_selected_names))) != self.enabled_selected_names:
            raise ValueError("enabled selected names must be sorted and unique")


def _toml_string(value: str) -> str:
    """Encode a derived path without allowing raw TOML or control characters."""

    absolute_posix_path(value)
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ArtifactProjectionError("skill config path must be valid UTF-8") from exc
    if any(
        ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F
        for character in value
    ):
        raise ArtifactProjectionError("skill config path contains a control character")
    return json.dumps(value, ensure_ascii=True)


def _locked_skills_root(codex_home: Path) -> Path:
    root = canonical_existing_directory(codex_home / "skills", "isolated skills root")
    if root.parent != codex_home or stat.S_IMODE(os.lstat(root).st_mode) != 0o500:
        raise ArtifactProjectionError("isolated skills root must be an exact locked directory")
    return root


def _verified_selected(
    selected: tuple[MaterializedSkill, ...],
    codex_home: Path,
    limits: FilesystemLimits,
) -> tuple[MaterializedSkill, ...]:
    if (
        type(selected) is not tuple
        or len(selected) > 128
        or any(type(item) is not MaterializedSkill for item in selected)
    ):
        raise ArtifactProjectionError("selected skill config entries are invalid or unbounded")
    names = [item.name for item in selected]
    if len(names) != len(set(names)) or set(names) & set(REVIEWED_SYSTEM_SKILLS_0_144_3):
        raise ArtifactProjectionError("selected skill config names must be unique and non-system")
    ordered = tuple(sorted(selected, key=lambda item: item.name))
    for item in ordered:
        expected_path = codex_home / "skills" / item.name / "SKILL.md"
        if Path(item.manifest_path) != expected_path:
            raise ArtifactProjectionError("selected skill path is outside the isolated skill root")
        try:
            directory = os.lstat(expected_path.parent)
            manifest = os.lstat(expected_path)
        except OSError as exc:
            raise ArtifactProjectionError("selected skill artifact is unavailable") from exc
        if not stat.S_ISDIR(directory.st_mode) or stat.S_IMODE(directory.st_mode) != 0o500:
            raise ArtifactProjectionError("selected skill directory is not locked")
        if not stat.S_ISREG(manifest.st_mode) or stat.S_IMODE(manifest.st_mode) != 0o400:
            raise ArtifactProjectionError("selected skill manifest is not locked and non-executable")
        capture = capture_directory(expected_path.parent, limits, reject_controls=True)
        manifest_digest = f"sha256:{capture.file('SKILL.md').content_digest}"
        if capture.accounting.digest != item.directory_digest or manifest_digest != item.manifest_digest:
            raise ArtifactProjectionError("selected skill artifact changed before config projection")
    return ordered


def _render_fragment(codex_home: Path, selected: tuple[MaterializedSkill, ...]) -> bytes:
    entries: list[tuple[str, bool]] = [
        (str(codex_home / "skills" / ".system" / name / "SKILL.md"), False)
        for name in REVIEWED_SYSTEM_SKILLS_0_144_3
    ]
    entries.extend((item.manifest_path, True) for item in selected)
    lines = [
        f"# Boltrig defense in depth for Codex {CODEX_SKILL_POLICY_VERSION}.",
        "# A force-reloaded exact enabled-set attestation remains authoritative.",
    ]
    for path, enabled in entries:
        lines.extend(
            (
                "",
                "[[skills.config]]",
                f"path = {_toml_string(path)}",
                f"enabled = {'true' if enabled else 'false'}",
            )
        )
    encoded = ("\n".join(lines) + "\n").encode("utf-8")
    if len(encoded) > MAX_SKILL_CONFIG_BYTES:
        raise ArtifactProjectionError("skill config exceeds its bounded size")
    return encoded


def _validated_fragment(
    selected: tuple[MaterializedSkill, ...],
    *,
    cell_root: Path,
    codex_home: Path,
    limits: FilesystemLimits,
) -> tuple[Path, tuple[MaterializedSkill, ...], bytes]:
    cell = canonical_existing_directory(cell_root, "cell root")
    home = canonical_existing_directory(codex_home, "Codex home")
    if home.parent != cell:
        raise ArtifactProjectionError("Codex home must be an exact child of the cell root")
    if stat.S_IMODE(os.lstat(home).st_mode) != 0o700:
        raise ArtifactProjectionError("Codex home must be private")
    _locked_skills_root(home)
    ordered = _verified_selected(selected, home, limits)
    return home, ordered, _render_fragment(home, ordered)


def render_skill_config_fragment(
    selected: tuple[MaterializedSkill, ...],
    *,
    cell_root: Path,
    codex_home: Path,
    limits: FilesystemLimits = FilesystemLimits(),
) -> bytes:
    """Render validated skill tables for deterministic full-config composition."""

    return _validated_fragment(
        selected,
        cell_root=cell_root,
        codex_home=codex_home,
        limits=limits,
    )[2]


def _write_all(descriptor: int, contents: bytes) -> None:
    offset = 0
    while offset < len(contents):
        written = os.write(descriptor, contents[offset:])
        if written < 1:
            raise ArtifactProjectionError("skill config write did not make progress")
        offset += written


def _read_all(descriptor: int, expected_bytes: int) -> bytes:
    chunks: list[bytes] = []
    remaining = expected_bytes + 1
    while remaining and (chunk := os.read(descriptor, remaining)):
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _unlink_our_file(home_fd: int, file_fd: int) -> None:
    try:
        opened = os.fstat(file_fd)
        current = os.stat("config.toml", dir_fd=home_fd, follow_symlinks=False)
        if stat.S_ISREG(current.st_mode) and (opened.st_dev, opened.st_ino) == (
            current.st_dev,
            current.st_ino,
        ):
            os.unlink("config.toml", dir_fd=home_fd)
            os.fsync(home_fd)
    except OSError:
        pass


def _same_inode(first: os.stat_result, second: os.stat_result) -> bool:
    return (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)


def _verify_written_config(
    codex_home: Path,
    home_fd: int,
    file_fd: int,
    expected_home: os.stat_result,
    contents: bytes,
) -> None:
    opened_home = os.fstat(home_fd)
    current_home = os.lstat(codex_home)
    opened_file = os.fstat(file_fd)
    current_file = os.stat("config.toml", dir_fd=home_fd, follow_symlinks=False)
    if not _same_inode(expected_home, opened_home) or not _same_inode(opened_home, current_home):
        raise ArtifactProjectionError("Codex home changed during config projection")
    if (
        not stat.S_ISREG(opened_file.st_mode)
        or stat.S_IMODE(opened_file.st_mode) != 0o400
        or opened_file.st_size != len(contents)
        or not _same_inode(opened_file, current_file)
    ):
        raise ArtifactProjectionError("skill config changed during projection")
    os.lseek(file_fd, 0, os.SEEK_SET)
    if _read_all(file_fd, len(contents)) != contents:
        raise ArtifactProjectionError("skill config changed during projection")


def _write_exclusive_config(codex_home: Path, contents: bytes) -> None:
    directory_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    directory_flags |= getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    file_flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    file_flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    home_fd: int | None = None
    file_fd: int | None = None
    try:
        expected_home = os.lstat(codex_home)
        home_fd = os.open(codex_home, directory_flags)
        if not _same_inode(expected_home, os.fstat(home_fd)):
            raise ArtifactProjectionError("Codex home changed during config projection")
        file_fd = os.open("config.toml", file_flags, 0o600, dir_fd=home_fd)
        _write_all(file_fd, contents)
        os.fchmod(file_fd, 0o400)
        os.fsync(file_fd)
        _verify_written_config(codex_home, home_fd, file_fd, expected_home, contents)
        os.fsync(home_fd)
    except (OSError, ArtifactProjectionError) as exc:
        if home_fd is not None and file_fd is not None:
            _unlink_our_file(home_fd, file_fd)
        raise ArtifactProjectionError("skill config could not be projected exclusively") from exc
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if home_fd is not None:
            os.close(home_fd)


def project_skill_config(
    selected: tuple[MaterializedSkill, ...],
    *,
    cell_root: Path,
    codex_home: Path,
    limits: FilesystemLimits = FilesystemLimits(),
) -> SkillConfigProjection:
    """Create an exclusive 0400 config; force-reload attestation remains authoritative."""

    home, ordered, contents = _validated_fragment(
        selected,
        cell_root=cell_root,
        codex_home=codex_home,
        limits=limits,
    )
    _write_exclusive_config(home, contents)
    return SkillConfigProjection(
        config_path=str(home / "config.toml"),
        config_digest=f"sha256:{hashlib.sha256(contents).hexdigest()}",
        codex_version=CODEX_SKILL_POLICY_VERSION,
        disabled_system_names=REVIEWED_SYSTEM_SKILLS_0_144_3,
        enabled_selected_names=tuple(item.name for item in ordered),
    )


__all__ = [
    "CODEX_SKILL_POLICY_VERSION",
    "MAX_SKILL_CONFIG_BYTES",
    "REVIEWED_SYSTEM_SKILLS_0_144_3",
    "SkillConfigProjection",
    "project_skill_config",
    "render_skill_config_fragment",
]
