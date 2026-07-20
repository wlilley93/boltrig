"""Fail-closed filesystem, binary, and environment policy for Codex cells."""

from __future__ import annotations

import hashlib
import os
import posixpath
import pwd
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from . import codex_protocol as wire
from .bounded_filesystem import (
    ArtifactProjectionError,
    DirectoryCapture,
    FilesystemLimits,
    capture_directory,
)
from .skill_artifacts import SanitizedWorkspaceProjection

CODEX_CLI_VERSION = "0.144.3"
CODEX_CLI_TARGET = "x86_64-unknown-linux-musl"
CODEX_CLI_SHA256 = "37e6f5953f191b04f7b62cb07dae90f51d0947ad89f0355665b421fbde28700b"
CODEX_AUTH_ENVIRONMENT_KEY = "CODEX_ACCESS_TOKEN"
MAX_CODEX_ACCESS_TOKEN_BYTES = 16 * 1024
_MINIMAL_PATH = "/usr/bin:/bin"
CODEX_WORKSPACE_LIMITS = FilesystemLimits()


class CodexCellPolicyError(wire.CodexAppServerError):
    """A cell path, binary, or environment violated supervisor policy."""


@dataclass(frozen=True)
class CodexCellLayout:
    """Pre-provisioned cell layout whose workspace was sanitized upstream.

    This value is an admission seam, not a builder.  The supervisor never
    creates, projects, copies, or trusts any of these paths.
    """

    phase_id: str
    cell_id: str
    stack_root: Path
    cell_root: Path
    workspace_projection: SanitizedWorkspaceProjection
    home: Path
    codex_home: Path

    @property
    def workspace(self) -> Path:
        return Path(self.workspace_projection.workspace_path)

    @property
    def workspace_digest(self) -> str:
        return self.workspace_projection.workspace_digest


class CodexUpstreamAuth:
    """Supervisor-managed upstream Codex authentication, always redacted."""

    __slots__ = ("_secret",)

    def __init__(self, secret: str) -> None:
        try:
            encoded = secret.encode("utf-8") if type(secret) is str else b""
        except UnicodeError:
            encoded = b""
        if (
            type(secret) is not str
            or not secret
            or secret != secret.strip()
            or "\x00" in secret
            or "\n" in secret
            or "\r" in secret
            or not encoded
            or len(encoded) > MAX_CODEX_ACCESS_TOKEN_BYTES
        ):
            raise ValueError("upstream Codex auth secret is invalid")
        self._secret = secret

    def __repr__(self) -> str:
        return "CodexUpstreamAuth(<redacted>)"

    def add_to(self, environment: dict[str, str]) -> None:
        environment[CODEX_AUTH_ENVIRONMENT_KEY] = self._secret

    def __reduce__(self) -> NoReturn:
        raise TypeError("upstream Codex auth cannot be serialized")


class PinnedCodexBinary:
    """One held, reviewed executable descriptor; the pathname is audit-only."""

    __slots__ = ("path", "sha256", "version", "target", "_descriptor")

    def __init__(self, path: Path, sha256: str, descriptor: int) -> None:
        if type(descriptor) is not int or descriptor < 0:
            raise ValueError("pinned Codex descriptor must be a non-negative integer")
        self.path = path
        self.sha256 = sha256
        self.version = CODEX_CLI_VERSION
        self.target = CODEX_CLI_TARGET
        self._descriptor = descriptor

    def fileno(self) -> int:
        if self._descriptor < 0:
            raise CodexCellPolicyError("pinned Codex descriptor is closed")
        return self._descriptor

    @property
    def execution_path(self) -> str:
        return f"/proc/self/fd/{self.fileno()}"

    def close(self) -> None:
        descriptor, self._descriptor = self._descriptor, -1
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                raise CodexCellPolicyError("pinned Codex descriptor could not be closed") from None

    def __del__(self) -> None:
        descriptor, self._descriptor = self._descriptor, -1
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _identifier(label: str, value: object) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise CodexCellPolicyError(f"{label} must be a non-empty trimmed string")
    return value


def normalized_absolute_path(label: str, value: object) -> Path:
    if not isinstance(value, Path):
        raise CodexCellPolicyError(f"{label} must be a pathlib Path")
    rendered = value.as_posix()
    if (
        not rendered
        or "\x00" in rendered
        or not posixpath.isabs(rendered)
        or rendered.startswith("//")
        or posixpath.normpath(rendered) != rendered
        or Path(rendered) != value
    ):
        raise CodexCellPolicyError(f"{label} must be a normalized absolute POSIX path")
    return value


def _contains(parent: Path, child: Path) -> bool:
    return child != parent and child.is_relative_to(parent)


def _overlaps(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _personal_home() -> Path:
    try:
        return normalized_absolute_path("account home", Path(pwd.getpwuid(os.geteuid()).pw_dir))
    except (KeyError, OSError) as exc:
        raise CodexCellPolicyError("cannot resolve the service account home") from exc


def _require_owned_directory(label: str, path: Path, expected_mode: int) -> None:
    try:
        details = path.lstat()
    except OSError:
        raise CodexCellPolicyError(f"{label} is not an accessible directory") from None
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
        raise CodexCellPolicyError(f"{label} must be a regular non-symlink directory")
    try:
        if path.resolve(strict=True) != path:
            raise CodexCellPolicyError(f"{label} must not traverse symlinks")
    except OSError:
        raise CodexCellPolicyError(f"{label} could not be resolved safely") from None
    if details.st_uid != os.geteuid():
        raise CodexCellPolicyError(f"{label} must be owned by the supervisor account")
    if stat.S_IMODE(details.st_mode) != expected_mode:
        raise CodexCellPolicyError(f"{label} has an unsafe mode")


def _require_projected_file(path: Path, *, executable: bool) -> None:
    try:
        details = path.lstat()
    except OSError:
        raise CodexCellPolicyError("sanitized workspace entry is unavailable") from None
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode):
        raise CodexCellPolicyError("sanitized workspace contains an unsafe entry")
    if details.st_uid != os.geteuid():
        raise CodexCellPolicyError("sanitized workspace entry has an unsafe owner")
    expected_mode = 0o500 if executable else 0o400
    if stat.S_IMODE(details.st_mode) != expected_mode:
        raise CodexCellPolicyError("sanitized workspace entry has an unsafe mode")


def _require_read_only_capture(workspace: Path, capture: DirectoryCapture) -> None:
    _require_owned_directory("workspace", workspace, 0o500)
    for relative in capture.directories:
        _require_owned_directory("sanitized workspace directory", workspace / relative, 0o500)
    for item in capture.files:
        _require_projected_file(workspace / item.relative_path, executable=item.executable)


def attest_workspace_projection(
    projection: object,
    limits: FilesystemLimits = CODEX_WORKSPACE_LIMITS,
) -> None:
    """Recapture an immutable projection and match its authenticated accounting."""

    if type(projection) is not SanitizedWorkspaceProjection:
        raise CodexCellPolicyError("workspace projection has an invalid type")
    value = projection
    workspace = normalized_absolute_path("workspace", Path(value.workspace_path))
    try:
        first = capture_directory(workspace, limits, reject_controls=True)
        _require_read_only_capture(workspace, first)
        first_accounting = first.accounting
        del first
        second = capture_directory(workspace, limits, reject_controls=True)
        _require_read_only_capture(workspace, second)
    except ArtifactProjectionError:
        raise CodexCellPolicyError("sanitized workspace re-attestation failed") from None
    if first_accounting != second.accounting:
        raise CodexCellPolicyError("sanitized workspace changed during re-attestation")
    expected = (value.workspace_digest, value.file_count, value.total_bytes)
    actual = (
        second.accounting.digest,
        second.accounting.file_count,
        second.accounting.total_bytes,
    )
    if actual != expected:
        raise CodexCellPolicyError("sanitized workspace does not match its projection")


# The read-only reasoning lane's workspace is always EMPTY, so its projection is a
# constant: the sha256 of nothing, zero files, zero bytes. Defined once (and drift-
# tested against a real capture_directory of an empty dir) so the per-cell path can
# assert the projection without the filesystem read the capless API cannot perform
# on a 0700 cell-uid slot.
EMPTY_WORKSPACE_DIGEST = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
EMPTY_WORKSPACE_FILE_COUNT = 0
EMPTY_WORKSPACE_TOTAL_BYTES = 0


def attest_empty_workspace_projection(projection: object) -> None:
    """Assert a projection is the known EMPTY read-only workspace, without any fs read.

    Under per-cell uids the workspace is a 0700 cell-uid dir the API cannot capture,
    but the read-only lane never populates it, so its projection must be exactly the
    empty constant. This pure check preserves the guarantee the capture-based
    re-attestation gives on the in-process path: that the workspace is what the
    admission recorded (here, provably empty).
    """

    if type(projection) is not SanitizedWorkspaceProjection:
        raise CodexCellPolicyError("workspace projection has an invalid type")
    actual = (projection.workspace_digest, projection.file_count, projection.total_bytes)
    expected = (EMPTY_WORKSPACE_DIGEST, EMPTY_WORKSPACE_FILE_COUNT, EMPTY_WORKSPACE_TOTAL_BYTES)
    if actual != expected:
        raise CodexCellPolicyError("per-cell workspace projection is not the empty constant")


def _file_identity(details: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        details.st_dev,
        details.st_ino,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
    )


def validate_cell_layout(
    layout: object, *, require_local_ownership: bool = True
) -> CodexCellLayout:
    if type(layout) is not CodexCellLayout:
        raise CodexCellPolicyError("layout must be a prevalidated CodexCellLayout")
    phase_id = _identifier("phase id", layout.phase_id)
    cell_id = _identifier("cell id", layout.cell_id)
    if type(layout.workspace_projection) is not SanitizedWorkspaceProjection:
        raise CodexCellPolicyError("layout requires a sanitized workspace projection")
    digest = _identifier("workspace digest", layout.workspace_digest)
    if not digest.startswith("sha256:") or len(digest) != 71:
        raise CodexCellPolicyError("workspace digest must be an exact sha256 digest")
    try:
        int(digest.removeprefix("sha256:"), 16)
    except ValueError:
        raise CodexCellPolicyError("workspace digest must be an exact sha256 digest") from None
    paths = {
        "stack root": normalized_absolute_path("stack root", layout.stack_root),
        "cell root": normalized_absolute_path("cell root", layout.cell_root),
        "workspace": normalized_absolute_path("workspace", layout.workspace),
        "home": normalized_absolute_path("home", layout.home),
        "CODEX_HOME": normalized_absolute_path("CODEX_HOME", layout.codex_home),
    }
    personal_home = _personal_home()
    if any(_overlaps(path, personal_home) for path in paths.values()):
        raise CodexCellPolicyError("cell paths must not overlap the service account home")
    if not _contains(paths["stack root"], paths["cell root"]):
        raise CodexCellPolicyError("cell root must be a child of the stack root")
    for label in ("workspace", "home", "CODEX_HOME"):
        if not _contains(paths["cell root"], paths[label]):
            raise CodexCellPolicyError(f"{label} must be a child of the cell root")
    isolated = (paths["workspace"], paths["home"], paths["CODEX_HOME"])
    if any(
        _overlaps(left, right)
        for index, left in enumerate(isolated)
        for right in isolated[index + 1 :]
    ):
        raise CodexCellPolicyError("workspace, HOME, and CODEX_HOME must not overlap")
    # The ownership/mode leg. On the per-cell path the tree is owned by the cell uid
    # (2000N) in a 0700 slot the API cannot traverse, so these exact lstat/resolve/
    # uid/mode checks are performed cell-uid-side by the spawner's provisioning child
    # (cell_spawner._verify_owned) - the only euid that can see the tree. Skipping
    # here therefore relocates the checks, it does not drop them. In-process keeps
    # them local. Every path-shape/containment/overlap check above always runs.
    if require_local_ownership:
        for label, path in paths.items():
            _require_owned_directory(label, path, 0o500 if label == "workspace" else 0o700)
    return CodexCellLayout(
        phase_id=phase_id,
        cell_id=cell_id,
        stack_root=paths["stack root"],
        cell_root=paths["cell root"],
        workspace_projection=layout.workspace_projection,
        home=paths["home"],
        codex_home=paths["CODEX_HOME"],
    )


def verify_pinned_binary(path: object) -> PinnedCodexBinary:
    binary = normalized_absolute_path("Codex binary", path)
    try:
        details = binary.lstat()
    except OSError:
        raise CodexCellPolicyError("Codex binary is not accessible") from None
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode):
        raise CodexCellPolicyError("Codex binary must be a regular non-symlink file")
    try:
        if binary.resolve(strict=True) != binary:
            raise CodexCellPolicyError("Codex binary must not traverse symlinks")
    except OSError:
        raise CodexCellPolicyError("Codex binary could not be resolved safely") from None
    if not os.access(binary, os.X_OK):
        raise CodexCellPolicyError("Codex binary must be executable")
    if stat.S_IMODE(details.st_mode) & 0o022:
        raise CodexCellPolicyError("Codex binary must not be group- or world-writable")
    digest = hashlib.sha256()
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(binary, flags)
    except OSError:
        raise CodexCellPolicyError("Codex binary could not be verified") from None
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or _file_identity(opened) != _file_identity(details):
            raise CodexCellPolicyError("Codex binary changed while it was being verified")
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        if _file_identity(binary.lstat()) != _file_identity(details):
            raise CodexCellPolicyError("Codex binary changed while it was being verified")
        actual = digest.hexdigest()
        if actual != CODEX_CLI_SHA256:
            raise CodexCellPolicyError("Codex binary digest does not match the reviewed pin")
        return PinnedCodexBinary(binary, actual, descriptor)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def sanitized_environment(
    layout: CodexCellLayout, auth: CodexUpstreamAuth | None
) -> dict[str, str]:
    environment = {
        "CODEX_HOME": layout.codex_home.as_posix(),
        "HOME": layout.home.as_posix(),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": _MINIMAL_PATH,
    }
    if auth is not None:
        if type(auth) is not CodexUpstreamAuth:
            raise CodexCellPolicyError("auth must be supervisor-managed Codex auth")
        auth.add_to(environment)
    return environment
