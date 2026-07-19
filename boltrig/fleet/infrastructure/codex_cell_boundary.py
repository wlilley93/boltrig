"""The named, kernel-enforced per-cell isolation boundary for Codex cells.

[2026] VJS-CC-VJS 5. Kernel peer attestation proves the PROVENANCE of a
connection, not the INTEGRITY of the program that makes it, so SO_PEERCRED
ancestry attestation isolates cells ONLY IF every attestation input is protected
from every other cell by a kernel-enforced boundary.

Every Codex cell shares one uid, and under a shared uid a file MODE is not a
boundary at all: the owning uid may chmod, unlink and rename anything it owns, so
a 0700 helper inside a 0700 cell root stops nothing between siblings. The kernel
container runs read_only with cap_drop ALL and no-new-privileges, so it holds
neither CAP_SETUID (no per-cell uids) nor CAP_SYS_ADMIN (no per-cell read-only
binds). Exactly ONE boundary is therefore available to it:

    a file owned by another account, in a directory chain this account cannot
    write, on the read-only image mount.

That is where the single shared auth helper now lives, extending the rule the
pinned Codex binary already relies on. This module resolves that helper, PROVES
at startup (it never assumes) that the boundary is in force by asking the kernel
itself, names the mechanism, and fails closed when it is absent.

WHAT THIS DELIBERATELY DOES NOT CLAIM: the cell's config.toml carries
``auth.command`` and must sit at ``$CODEX_HOME/config.toml`` inside a directory
the cell uid owns, so a sibling cell can still replace it and name a different
program. ``config_toml_protected`` is therefore False under this mechanism, and
callers MUST refuse to run mutually distrusting cells concurrently while it is
False. Reporting that honestly is the point of the field.
"""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

SHARED_HELPER_ENV_KEY = "BOLTRIG_CODEX_AUTH_HELPER"
DEFAULT_SHARED_HELPER_PATH = Path("/opt/boltrig/codex/model_auth_helper")
PTRACE_SCOPE_PATH = Path("/proc/sys/kernel/yama/ptrace_scope")
MINIMUM_PTRACE_SCOPE = 1
BOUNDARY_MECHANISM = "root-owned-shared-helper-on-read-only-image-mount"
_MAX_HELPER_BYTES = 256 * 1024


class CodexCellBoundaryError(RuntimeError):
    """The named per-cell isolation boundary is absent, so nothing may start."""


@dataclass(frozen=True, slots=True)
class CellIsolationBoundary:
    """One proved statement about the boundary in force, carrying its evidence.

    ``config_toml_protected`` is a load-bearing admission, not a formality: it is
    False under this mechanism because config.toml cannot be taken out of a
    cell-uid-owned directory without privileges this container does not hold.
    """

    mechanism: str
    helper_path: Path
    helper_sha256: str
    helper_on_read_only_mount: bool
    ptrace_scope: int
    config_toml_protected: bool


def resolve_shared_helper_path(env: Mapping[str, str] | None = None) -> Path:
    """Resolve the single shared helper path, defaulting to the image location.

    The env override exists so a test or a differently laid out image can point at
    another root-owned path; it can only move the assertion target, never weaken
    it, because every check below is applied to whatever it names.
    """

    source = env if env is not None else os.environ
    raw = source.get(SHARED_HELPER_ENV_KEY)
    if raw is None or not raw.strip():
        return DEFAULT_SHARED_HELPER_PATH
    trimmed = raw.strip()
    candidate = Path(trimmed)
    if not candidate.is_absolute() or os.path.normpath(trimmed) != trimmed:
        raise CodexCellBoundaryError("shared auth helper path must be normalized and absolute")
    return candidate


def _require_not_writable_by_us(label: str, path: Path) -> None:
    """Ask the KERNEL whether our effective ids can write ``path``.

    ``effective_ids=True`` makes faccessat answer for the effective uid, gid and
    supplementary groups, which is the only question worth asking: a mode bit we
    could chmod away is no boundary, but a file another account owns on a mount we
    cannot write is one.
    """

    if os.access not in os.supports_effective_ids:
        raise CodexCellBoundaryError(
            f"{label} writability cannot be decided for effective ids on this platform"
        )
    if os.access(path, os.W_OK, effective_ids=True):
        raise CodexCellBoundaryError(f"{label} is writable by this account")


def _require_foreign_owner(label: str, details: os.stat_result) -> None:
    """Refuse anything our own euid owns: an owner can always restore write."""

    if details.st_uid == os.geteuid():
        raise CodexCellBoundaryError(
            f"{label} is owned by this account, so its mode is no boundary"
        )
    if stat.S_IMODE(details.st_mode) & 0o022:
        raise CodexCellBoundaryError(f"{label} is group- or world-writable")


def _lstat_no_symlink(label: str, path: Path) -> os.stat_result:
    try:
        details = path.lstat()
    except OSError:
        raise CodexCellBoundaryError(f"{label} is not accessible") from None
    if stat.S_ISLNK(details.st_mode):
        raise CodexCellBoundaryError(f"{label} must not be a symlink")
    return details


def _assert_immutable_chain(helper_path: Path) -> None:
    """Prove the helper AND every ancestor directory are beyond our write reach.

    A writable parent is as good as a writable file: a cell that can write the
    containing directory can unlink the helper and put its own program there, so
    the whole chain up to the root is checked, not just the leaf.
    """

    for ancestor in helper_path.parents:
        label = f"shared auth helper ancestor {ancestor}"
        details = _lstat_no_symlink(label, ancestor)
        if not stat.S_ISDIR(details.st_mode):
            raise CodexCellBoundaryError(f"{label} is not a directory")
        _require_foreign_owner(label, details)
        _require_not_writable_by_us(label, ancestor)


def _digest_helper(helper_path: Path) -> str:
    """Digest the resolved helper so the config receipt still binds the program."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(helper_path, flags)
    except OSError:
        raise CodexCellBoundaryError("shared auth helper could not be opened") from None
    digest = hashlib.sha256()
    total = 0
    try:
        while chunk := os.read(descriptor, 65536):
            total += len(chunk)
            if total > _MAX_HELPER_BYTES:
                raise CodexCellBoundaryError("shared auth helper exceeds its byte bound")
            digest.update(chunk)
    finally:
        os.close(descriptor)
    return "sha256:" + digest.hexdigest()


def assert_ptrace_scope(
    path: Path = PTRACE_SCOPE_PATH, minimum: int = MINIMUM_PTRACE_SCOPE
) -> int:
    """Assert Yama restricted ptrace, failing closed when it cannot be read (G5).

    Under one uid, ptrace and process_vm_readv are the same-uid introspection route
    between sibling cells; both are gated by PTRACE_MODE_ATTACH, which Yama
    restricts to descendants at scope 1 or above. Cells are siblings, so scope 1
    denies A any read of B's address space. This sysctl is NOT namespaced: a
    container reads the HOST value and cannot set it, so this assertion proves a
    deployment precondition and does not create one. An unreadable or too-low value
    is fatal, never a warning.
    """

    if type(minimum) is not int or minimum < 0:
        raise CodexCellBoundaryError("minimum ptrace scope must be a non-negative integer")
    try:
        raw = path.read_text(encoding="ascii").strip()
    except OSError:
        raise CodexCellBoundaryError(
            "yama ptrace_scope is unreadable, so ptrace is unproved"
        ) from None
    try:
        scope = int(raw)
    except ValueError:
        raise CodexCellBoundaryError("yama ptrace_scope is malformed") from None
    if scope < minimum:
        raise CodexCellBoundaryError(
            f"yama ptrace_scope is {scope}, below the required {minimum} for shared-uid cells"
        )
    return scope


def assert_cell_isolation_boundary(
    *,
    stack_root: Path,
    env: Mapping[str, str] | None = None,
    require_ptrace_scope: bool = True,
) -> CellIsolationBoundary:
    """Prove the named boundary is in force right now, or refuse to proceed (G4).

    Verified, never assumed: the helper is a regular non-symlink file owned by
    another account, executable by us, not writable by our effective ids, sitting
    in a directory chain none of which we can write, and lying entirely OUTSIDE the
    mutable stack root every cell can write.
    """

    if not isinstance(stack_root, Path) or not stack_root.is_absolute():
        raise CodexCellBoundaryError("stack_root must be an absolute Path")
    helper_path = resolve_shared_helper_path(env)
    details = _lstat_no_symlink("shared auth helper", helper_path)
    if not stat.S_ISREG(details.st_mode):
        raise CodexCellBoundaryError("shared auth helper must be a regular file")
    try:
        if helper_path.resolve(strict=True) != helper_path:
            raise CodexCellBoundaryError("shared auth helper must not traverse symlinks")
    except OSError:
        raise CodexCellBoundaryError("shared auth helper could not be resolved safely") from None
    if helper_path.is_relative_to(stack_root):
        raise CodexCellBoundaryError("shared auth helper must lie outside the mutable stack root")
    _require_foreign_owner("shared auth helper", details)
    _require_not_writable_by_us("shared auth helper", helper_path)
    if not os.access(helper_path, os.X_OK, effective_ids=True):
        raise CodexCellBoundaryError("shared auth helper is not executable by this account")
    _assert_immutable_chain(helper_path)
    scope = assert_ptrace_scope() if require_ptrace_scope else -1
    return CellIsolationBoundary(
        mechanism=BOUNDARY_MECHANISM,
        helper_path=helper_path,
        helper_sha256=_digest_helper(helper_path),
        helper_on_read_only_mount=bool(os.statvfs(helper_path).f_flag & os.ST_RDONLY),
        ptrace_scope=scope,
        # Honest and load-bearing: config.toml stays in a cell-uid-owned CODEX_HOME.
        config_toml_protected=False,
    )


__all__ = [
    "BOUNDARY_MECHANISM",
    "CellIsolationBoundary",
    "CodexCellBoundaryError",
    "DEFAULT_SHARED_HELPER_PATH",
    "MINIMUM_PTRACE_SCOPE",
    "PTRACE_SCOPE_PATH",
    "SHARED_HELPER_ENV_KEY",
    "assert_cell_isolation_boundary",
    "assert_ptrace_scope",
    "resolve_shared_helper_path",
]
