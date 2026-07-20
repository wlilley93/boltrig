"""Bounded Linux kernel and proc identity capture for local Unix peers.

This module only observes process identity.  It does not listen on a socket,
mint a credential, or decide model authority.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
from typing import Protocol

MAX_PROC_FILE_BYTES = 8_192
MAX_PROC_LINK_BYTES = 128
MAX_CGROUP_LINES = 16
MAX_CGROUP_LINE_BYTES = 1_024
MAX_LINUX_ID = 2**32 - 2
MAX_SIGNED_BIGINT = 2**63 - 1

_BOOT_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
_CGROUP_CONTROLLER = re.compile(r"[A-Za-z0-9_.=-]+\Z")
_PID_NAMESPACE = re.compile(r"pid:\[([1-9][0-9]{0,18})\]\Z")


class LinuxPeerIdentityError(RuntimeError):
    """Kernel or proc identity could not be captured safely."""


class ProcReader(Protocol):
    """Injectable bounded view of a proc filesystem."""

    def read_file(self, relative_path: str, *, max_bytes: int) -> str: ...

    def read_link(self, relative_path: str, *, max_bytes: int) -> str: ...


@dataclass(frozen=True, repr=False)
class PeerCredentials:
    pid: int
    uid: int
    gid: int

    def __post_init__(self) -> None:
        _positive("peer pid", self.pid)
        _linux_id("peer uid", self.uid)
        _linux_id("peer gid", self.gid)

    def __repr__(self) -> str:
        return "PeerCredentials(<kernel-observed>)"


@dataclass(frozen=True, repr=False)
class CapturedLinuxProcess:
    pid: int
    parent_pid: int
    start_ticks: int
    boot_id: str
    pid_namespace_inode: int
    cgroup_identity_digest: str
    uid: int
    gid: int

    def __post_init__(self) -> None:
        _positive("pid", self.pid)
        _nonnegative("parent pid", self.parent_pid)
        _positive("start ticks", self.start_ticks)
        if type(self.boot_id) is not str or _BOOT_ID.fullmatch(self.boot_id) is None:
            raise LinuxPeerIdentityError("invalid boot identity")
        _positive("pid namespace inode", self.pid_namespace_inode)
        if not _is_prefixed_sha256(self.cgroup_identity_digest):
            raise LinuxPeerIdentityError("invalid cgroup identity")
        _linux_id("uid", self.uid)
        _linux_id("gid", self.gid)

    def __repr__(self) -> str:
        return "CapturedLinuxProcess(<redacted>)"


class LinuxProcReader:
    """Read-only, byte-bounded proc reader rooted at ``/proc`` by default."""

    def __init__(self, root: Path = Path("/proc")) -> None:
        if not isinstance(root, Path) or not root.is_absolute():
            raise TypeError("proc root must be an absolute Path")
        self._root = root

    def read_file(self, relative_path: str, *, max_bytes: int) -> str:
        target = self._target(relative_path)
        limit = _read_limit(max_bytes)
        try:
            with target.open("rb", buffering=0) as handle:
                value = handle.read(limit + 1)
        except OSError as exc:
            raise LinuxPeerIdentityError("proc file unavailable") from exc
        if len(value) > limit:
            raise LinuxPeerIdentityError("proc file exceeds bound")
        try:
            return value.decode("ascii", errors="strict")
        except UnicodeError as exc:
            raise LinuxPeerIdentityError("proc file is not ASCII") from exc

    def read_link(self, relative_path: str, *, max_bytes: int) -> str:
        target = self._target(relative_path)
        limit = _read_limit(max_bytes)
        try:
            value = os.readlink(target)
            encoded = value.encode("ascii", errors="strict")
        except (OSError, UnicodeError) as exc:
            raise LinuxPeerIdentityError("proc link unavailable") from exc
        if len(encoded) > limit:
            raise LinuxPeerIdentityError("proc link exceeds bound")
        return value

    def _target(self, relative_path: str) -> Path:
        if (
            type(relative_path) is not str
            or not relative_path
            or relative_path.startswith("/")
            or ".." in Path(relative_path).parts
        ):
            raise LinuxPeerIdentityError("invalid proc path")
        return self._root.joinpath(*relative_path.split("/"))


def read_boot_id(reader: ProcReader) -> str:
    raw = reader.read_file("sys/kernel/random/boot_id", max_bytes=64)
    value = raw.strip("\n")
    if raw not in {value, value + "\n"} or _BOOT_ID.fullmatch(value) is None:
        raise LinuxPeerIdentityError("invalid boot identity")
    return value


def read_pid_namespace_inode(reader: ProcReader, pid: object = "self") -> int:
    """The pid-namespace inode for a process, defaulting to the caller's own.

    Reading ``/proc/<pid>/ns/pid`` of a DIFFERENT uid requires the process owner or
    CAP_SYS_PTRACE, neither of which the capless dropped API holds. But every cell
    the spawner forks lives in THIS container's single pid namespace (plain
    ``os.fork``, no ``CLONE_NEWPID`` - VJS-CC-VJS 7), so the inode is a container
    invariant identical read from any member. Callers that spawned the target
    themselves can therefore source it from ``self`` instead of a cross-uid read.
    """

    target = "self" if pid == "self" else str(_positive("pid", pid))
    return _parse_namespace(
        reader.read_link(f"{target}/ns/pid", max_bytes=MAX_PROC_LINK_BYTES)
    )


def capture_linux_process(
    reader: ProcReader,
    pid: int,
    *,
    expected_boot_id: str,
    pid_namespace_inode: int | None = None,
) -> CapturedLinuxProcess:
    safe_pid = _positive("pid", pid)
    if _BOOT_ID.fullmatch(expected_boot_id) is None:
        raise LinuxPeerIdentityError("invalid expected boot identity")
    prefix = str(safe_pid)
    first_stat = _parse_stat(reader.read_file(f"{prefix}/stat", max_bytes=4_096), safe_pid)
    uid, gid = _parse_status(reader.read_file(f"{prefix}/status", max_bytes=4_096))
    # A caller that knows the process shares its pid namespace (it forked it) may
    # supply the invariant inode directly, avoiding a cross-uid ns/pid read the
    # capless API cannot perform; otherwise read the target's own link.
    if pid_namespace_inode is not None:
        namespace = _positive("pid namespace inode", pid_namespace_inode)
    else:
        namespace = _parse_namespace(
            reader.read_link(f"{prefix}/ns/pid", max_bytes=MAX_PROC_LINK_BYTES)
        )
    cgroup = canonical_cgroup_digest(
        reader.read_file(f"{prefix}/cgroup", max_bytes=MAX_PROC_FILE_BYTES)
    )
    second_stat = _parse_stat(reader.read_file(f"{prefix}/stat", max_bytes=4_096), safe_pid)
    if first_stat != second_stat:
        raise LinuxPeerIdentityError("process identity changed during capture")
    return CapturedLinuxProcess(
        pid=safe_pid,
        parent_pid=first_stat[0],
        start_ticks=first_stat[1],
        boot_id=expected_boot_id,
        pid_namespace_inode=namespace,
        cgroup_identity_digest=cgroup,
        uid=uid,
        gid=gid,
    )


def canonical_cgroup_digest(raw: str) -> str:
    if type(raw) is not str:
        raise LinuxPeerIdentityError("invalid cgroup data")
    try:
        encoded = raw.encode("ascii", errors="strict")
    except UnicodeError as exc:
        raise LinuxPeerIdentityError("invalid cgroup data") from exc
    if len(encoded) > MAX_PROC_FILE_BYTES or _has_forbidden_control(raw, allow_tab=False):
        raise LinuxPeerIdentityError("invalid cgroup data")
    body = raw[:-1] if raw.endswith("\n") else raw
    lines = body.split("\n")
    if not lines or len(lines) > MAX_CGROUP_LINES or any(not line for line in lines):
        raise LinuxPeerIdentityError("invalid cgroup data")
    normalized = tuple(_normalize_cgroup_line(line) for line in lines)
    if len(set(normalized)) != len(normalized):
        raise LinuxPeerIdentityError("duplicate cgroup entry")
    canonical = "\n".join(sorted(normalized)).encode("ascii")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _parse_stat(raw: str, pid: int) -> tuple[int, int]:
    if type(raw) is not str or len(raw.encode("ascii", errors="ignore")) > 4_096:
        raise LinuxPeerIdentityError("invalid proc stat")
    value = raw.rstrip("\n")
    if raw not in {value, value + "\n"} or _has_forbidden_control(value, allow_tab=False):
        raise LinuxPeerIdentityError("invalid proc stat")
    closing = value.rfind(")")
    if not value.startswith(f"{pid} (") or closing < len(str(pid)) + 2:
        raise LinuxPeerIdentityError("invalid proc stat")
    fields = value[closing + 1 :].strip().split()
    if len(fields) < 20 or re.fullmatch(r"[A-Za-z]", fields[0]) is None:
        raise LinuxPeerIdentityError("invalid proc stat")
    parent = _decimal("parent pid", fields[1], allow_zero=True)
    start = _decimal("start ticks", fields[19], allow_zero=False)
    return parent, start


def _parse_status(raw: str) -> tuple[int, int]:
    if type(raw) is not str or _has_forbidden_control(raw, allow_tab=True):
        raise LinuxPeerIdentityError("invalid proc status")
    found: dict[str, int] = {}
    for line in raw.splitlines():
        if not line.startswith(("Uid:", "Gid:")):
            continue
        label, _, suffix = line.partition(":")
        values = suffix.split()
        if label in found or len(values) != 4:
            raise LinuxPeerIdentityError("invalid proc status")
        parsed = tuple(_decimal(label, item, allow_zero=True, linux_id=True) for item in values)
        if len(set(parsed)) != 1:
            raise LinuxPeerIdentityError("transitional process credentials rejected")
        found[label] = parsed[0]
    if set(found) != {"Uid", "Gid"}:
        raise LinuxPeerIdentityError("missing process credentials")
    return found["Uid"], found["Gid"]


def _parse_namespace(raw: str) -> int:
    if type(raw) is not str:
        raise LinuxPeerIdentityError("invalid pid namespace")
    matched = _PID_NAMESPACE.fullmatch(raw)
    if matched is None:
        raise LinuxPeerIdentityError("invalid pid namespace")
    return _decimal("pid namespace", matched.group(1), allow_zero=False)


def _normalize_cgroup_line(line: str) -> str:
    if len(line.encode("ascii")) > MAX_CGROUP_LINE_BYTES:
        raise LinuxPeerIdentityError("cgroup line exceeds bound")
    hierarchy, separator, remainder = line.partition(":")
    controllers, separator_two, path = remainder.partition(":")
    if not separator or not separator_two:
        raise LinuxPeerIdentityError("invalid cgroup entry")
    hierarchy_value = _decimal("cgroup hierarchy", hierarchy, allow_zero=True)
    controller_items = controllers.split(",") if controllers else []
    if any(_CGROUP_CONTROLLER.fullmatch(item) is None for item in controller_items):
        raise LinuxPeerIdentityError("invalid cgroup controller")
    if (hierarchy_value == 0) != (not controller_items):
        raise LinuxPeerIdentityError("invalid cgroup hierarchy")
    if len(set(controller_items)) != len(controller_items):
        raise LinuxPeerIdentityError("duplicate cgroup controller")
    if not path.startswith("/") or "//" in path or (path != "/" and path.endswith("/")):
        raise LinuxPeerIdentityError("invalid cgroup path")
    if any(part in {".", ".."} for part in path.split("/")):
        raise LinuxPeerIdentityError("invalid cgroup path")
    return f"{hierarchy_value}:{','.join(sorted(controller_items))}:{path}"


def _has_forbidden_control(value: str, *, allow_tab: bool) -> bool:
    allowed = {"\n"}
    if allow_tab:
        allowed.add("\t")
    return any(
        (ord(character) < 32 and character not in allowed) or ord(character) > 126
        for character in value
    )


def _decimal(label: str, value: str, *, allow_zero: bool, linux_id: bool = False) -> int:
    if not value or not value.isascii() or not value.isdecimal():
        raise LinuxPeerIdentityError(f"invalid {label}")
    parsed = int(value)
    maximum = MAX_LINUX_ID if linux_id else MAX_SIGNED_BIGINT
    minimum = 0 if allow_zero else 1
    if not minimum <= parsed <= maximum:
        raise LinuxPeerIdentityError(f"invalid {label}")
    return parsed


def _positive(label: str, value: object) -> int:
    if type(value) is not int or not 1 <= value <= MAX_SIGNED_BIGINT:
        raise LinuxPeerIdentityError(f"invalid {label}")
    return value


def _nonnegative(label: str, value: object) -> int:
    if type(value) is not int or not 0 <= value <= MAX_SIGNED_BIGINT:
        raise LinuxPeerIdentityError(f"invalid {label}")
    return value


def _linux_id(label: str, value: object) -> int:
    if type(value) is not int or not 0 <= value <= MAX_LINUX_ID:
        raise LinuxPeerIdentityError(f"invalid {label}")
    return value


def _read_limit(value: object) -> int:
    if type(value) is not int or not 1 <= value <= MAX_PROC_FILE_BYTES:
        raise LinuxPeerIdentityError("invalid proc read bound")
    return value


def _is_prefixed_sha256(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


__all__ = [
    "CapturedLinuxProcess",
    "LinuxPeerIdentityError",
    "LinuxProcReader",
    "PeerCredentials",
    "ProcReader",
    "canonical_cgroup_digest",
    "capture_linux_process",
    "read_pid_namespace_inode",
    "read_boot_id",
]
