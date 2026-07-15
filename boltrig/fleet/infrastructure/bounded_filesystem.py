"""Race-conscious, allocation-bounded directory capture primitives."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from boltrig.fleet.domain.skill_attestation import absolute_posix_path, sha256_digest

CONTROL_NAMES = frozenset({".agents", ".bzr", ".codex", ".git", ".hg", ".jj", ".svn"})
_READ_CHUNK = 64 * 1024


class ArtifactProjectionError(RuntimeError):
    """A source tree could not be safely captured into an isolated cell."""


@dataclass(frozen=True)
class FilesystemLimits:
    """Hard allocation and traversal ceilings for every captured directory."""

    max_files: int = 2048
    max_directories: int = 512
    max_total_bytes: int = 64 * 1024 * 1024
    max_file_bytes: int = 8 * 1024 * 1024
    max_depth: int = 16

    def __post_init__(self) -> None:
        values = (
            self.max_files,
            self.max_directories,
            self.max_total_bytes,
            self.max_file_bytes,
            self.max_depth,
        )
        if any(type(value) is not int or value < 1 for value in values):
            raise ValueError("filesystem limits must be positive integers")
        if self.max_file_bytes > self.max_total_bytes:
            raise ValueError("per-file limit cannot exceed the total-byte limit")


@dataclass(frozen=True)
class DirectoryDigest:
    """A deterministic bounded digest and its allocation accounting."""

    digest: str
    file_count: int
    directory_count: int
    total_bytes: int

    def __post_init__(self) -> None:
        sha256_digest(self.digest)
        values = (self.file_count, self.directory_count, self.total_bytes)
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("directory digest accounting must be non-negative integers")


@dataclass(frozen=True)
class FileCapture:
    relative_path: str
    contents: bytes
    executable: bool
    content_digest: str


@dataclass(frozen=True)
class DirectoryCapture:
    root: Path
    directories: tuple[str, ...]
    files: tuple[FileCapture, ...]
    accounting: DirectoryDigest

    def file(self, relative_path: str) -> FileCapture:
        for item in self.files:
            if item.relative_path == relative_path:
                return item
        raise ArtifactProjectionError("required skill manifest is missing")


@dataclass
class _ScanState:
    directories: list[str]
    files: list[FileCapture]
    total_bytes: int = 0


def canonical_existing_directory(path: Path, label: str) -> Path:
    spelling = absolute_posix_path(str(path))
    candidate = Path(spelling)
    try:
        metadata = os.lstat(candidate)
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ArtifactProjectionError(f"{label} is unavailable") from exc
    if not stat.S_ISDIR(metadata.st_mode) or resolved != candidate:
        raise ArtifactProjectionError(f"{label} must be a canonical non-symlink directory")
    return candidate


def exact_destination(cell_root: Path, destination: Path) -> tuple[Path, Path]:
    root = canonical_existing_directory(cell_root, "cell root")
    candidate = Path(absolute_posix_path(str(destination)))
    if candidate.parent != root or candidate == root:
        raise ArtifactProjectionError("destination must be an exact child of the cell root")
    if candidate.exists() or candidate.is_symlink():
        raise ArtifactProjectionError("destination must not already exist")
    return root, candidate


def paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _fingerprint(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _read_file_at(
    directory_fd: int,
    name: str,
    before: os.stat_result,
    remaining: int,
    limits: FilesystemLimits,
) -> bytes:
    if before.st_size > limits.max_file_bytes or before.st_size > remaining:
        raise ArtifactProjectionError("source tree exceeds the configured byte limit")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or _fingerprint(opened) != _fingerprint(before):
                raise ArtifactProjectionError("source file changed during capture")
            chunks: list[bytes] = []
            read_bytes = 0
            read_size = min(_READ_CHUNK, limits.max_file_bytes - read_bytes + 1)
            while chunk := stream.read(read_size):
                read_bytes += len(chunk)
                if read_bytes > before.st_size or read_bytes > limits.max_file_bytes:
                    raise ArtifactProjectionError("source file changed during capture")
                chunks.append(chunk)
            after = os.fstat(stream.fileno())
    except OSError as exc:
        raise ArtifactProjectionError("source file could not be safely read") from exc
    if _fingerprint(after) != _fingerprint(opened) or read_bytes != before.st_size:
        raise ArtifactProjectionError("source file changed during capture")
    return b"".join(chunks)


def _walk(
    directory_fd: int,
    relative: Path,
    depth: int,
    state: _ScanState,
    limits: FilesystemLimits,
    reject_controls: bool,
) -> None:
    if depth > limits.max_depth:
        raise ArtifactProjectionError("source tree exceeds the configured depth limit")
    before = os.fstat(directory_fd)
    try:
        entries: list[os.DirEntry[str]] = []
        with os.scandir(directory_fd) as iterator:
            for entry in iterator:
                entries.append(entry)
                if len(entries) > limits.max_files + limits.max_directories:
                    raise ArtifactProjectionError("source directory exceeds the entry-count limit")
        entries.sort(key=lambda item: item.name)
    except OSError as exc:
        raise ArtifactProjectionError("source directory could not be enumerated") from exc
    for entry in entries:
        if entry.name in CONTROL_NAMES:
            if reject_controls:
                raise ArtifactProjectionError("skill artifact contains a forbidden control path")
            continue
        _capture_entry(directory_fd, relative, depth, state, limits, reject_controls, entry)
    after = os.fstat(directory_fd)
    if _fingerprint(after) != _fingerprint(before):
        raise ArtifactProjectionError("source directory changed during capture")


def _capture_entry(
    directory_fd: int,
    relative: Path,
    depth: int,
    state: _ScanState,
    limits: FilesystemLimits,
    reject_controls: bool,
    entry: os.DirEntry[str],
) -> None:
    try:
        encoded_name = entry.name.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ArtifactProjectionError("source path is not valid UTF-8") from exc
    if len(encoded_name) > 255:
        raise ArtifactProjectionError("source path component exceeds the bounded length")
    child_relative = relative / entry.name
    if len(child_relative.as_posix().encode("utf-8")) > 4096:
        raise ArtifactProjectionError("source relative path exceeds the bounded length")
    try:
        metadata = entry.stat(follow_symlinks=False)
    except OSError as exc:
        raise ArtifactProjectionError("source entry changed during capture") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise ArtifactProjectionError("source tree contains a symbolic link")
    if stat.S_ISDIR(metadata.st_mode):
        state.directories.append(child_relative.as_posix())
        if len(state.directories) > limits.max_directories:
            raise ArtifactProjectionError("source tree exceeds the directory-count limit")
        _walk_child_directory(
            directory_fd,
            entry.name,
            metadata,
            child_relative,
            depth,
            state,
            limits,
            reject_controls,
        )
        return
    if not stat.S_ISREG(metadata.st_mode):
        raise ArtifactProjectionError("source tree contains a special file")
    if len(state.files) >= limits.max_files:
        raise ArtifactProjectionError("source tree exceeds the file-count limit")
    remaining = limits.max_total_bytes - state.total_bytes
    contents = _read_file_at(directory_fd, entry.name, metadata, remaining, limits)
    state.total_bytes += len(contents)
    state.files.append(
        FileCapture(
            relative_path=child_relative.as_posix(),
            contents=contents,
            executable=bool(metadata.st_mode & 0o111),
            content_digest=hashlib.sha256(contents).hexdigest(),
        )
    )


def _walk_child_directory(
    parent_fd: int,
    name: str,
    expected: os.stat_result,
    relative: Path,
    parent_depth: int,
    state: _ScanState,
    limits: FilesystemLimits,
    reject_controls: bool,
) -> None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_DIRECTORY", 0)
    child_fd: int | None = None
    try:
        child_fd = os.open(name, flags, dir_fd=parent_fd)
        opened = os.fstat(child_fd)
        if not stat.S_ISDIR(opened.st_mode) or _fingerprint(opened) != _fingerprint(expected):
            raise ArtifactProjectionError("source directory changed during capture")
        _walk(child_fd, relative, parent_depth + 1, state, limits, reject_controls)
    except OSError as exc:
        raise ArtifactProjectionError("source directory could not be safely opened") from exc
    finally:
        if child_fd is not None:
            os.close(child_fd)


def capture_directory(
    root: Path,
    limits: FilesystemLimits,
    *,
    reject_controls: bool,
) -> DirectoryCapture:
    canonical = canonical_existing_directory(root, "source root")
    state = _ScanState(directories=[], files=[])
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_DIRECTORY", 0)
    root_fd: int | None = None
    try:
        root_fd = os.open(canonical, flags)
        _walk(root_fd, Path(), 0, state, limits, reject_controls)
    except OSError as exc:
        raise ArtifactProjectionError("source root could not be safely opened") from exc
    finally:
        if root_fd is not None:
            os.close(root_fd)
    digest = hashlib.sha256()
    for relative in sorted(state.directories):
        digest.update(b"D\0" + relative.encode("utf-8") + b"\0")
    for item in sorted(state.files, key=lambda value: value.relative_path):
        digest.update(b"F\0" + item.relative_path.encode("utf-8") + b"\0")
        digest.update(str(len(item.contents)).encode("ascii") + b"\0")
        digest.update(b"X\0" if item.executable else b"N\0")
        digest.update(item.content_digest.encode("ascii") + b"\0")
    accounting = DirectoryDigest(
        digest=f"sha256:{digest.hexdigest()}",
        file_count=len(state.files),
        directory_count=len(state.directories),
        total_bytes=state.total_bytes,
    )
    return DirectoryCapture(canonical, tuple(state.directories), tuple(state.files), accounting)


def digest_directory(
    root: Path,
    limits: FilesystemLimits = FilesystemLimits(),
    *,
    reject_controls: bool = True,
) -> DirectoryDigest:
    """Recompute a bounded directory digest without following unsafe entries."""

    return capture_directory(root, limits, reject_controls=reject_controls).accounting


def write_capture(capture: DirectoryCapture, destination: Path) -> None:
    for relative in sorted(capture.directories, key=lambda value: (value.count("/"), value)):
        (destination / relative).mkdir(mode=0o700)
    for item in capture.files:
        target = destination / item.relative_path
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(target, flags, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(item.contents)
            stream.flush()
            os.fsync(stream.fileno())
        target.chmod(0o500 if item.executable else 0o400)
    for relative in sorted(capture.directories, key=lambda value: value.count("/"), reverse=True):
        (destination / relative).chmod(0o500)
    destination.chmod(0o500)


__all__ = [
    "ArtifactProjectionError",
    "CONTROL_NAMES",
    "DirectoryCapture",
    "DirectoryDigest",
    "FileCapture",
    "FilesystemLimits",
    "canonical_existing_directory",
    "capture_directory",
    "digest_directory",
    "exact_destination",
    "paths_overlap",
    "write_capture",
]
