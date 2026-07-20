"""Privilege state for the per-cell uid mode ([2026] VJS-CC-VJS 7 J3/J5).

The court granted CAP_SETUID and CAP_SETGID with the container at uid 0, and
conditioned the whole grant on privilege separation. The reason is specific and
worth stating where the code lives: ``CodexCellSupervisor._spawn`` is an
in-process asyncio spawn inside the uvicorn API process, so simply setting
``user: 0`` would make uid 0 the identity of the ENTIRE API, including the paths
that parse untrusted model output. The order forbids that outright.

So this module supplies the two halves of the condition:

- :func:`drop_privileges` moves a process to an unprivileged uid and empties its
  capability sets;
- :func:`assert_unprivileged` refuses to continue if a process that must be
  unprivileged is not, and it reads the kernel's own answer from ``/proc`` rather
  than trusting that the drop was called.

WHAT MAKES A DROPPED PROCESS UNABLE TO CLIMB BACK, stated correctly because the
court struck out the version I pled first (J6 forbids repeating it): it is NOT
that an empty permitted set makes the capability BOUNDING set inert. The bounding
set is precisely the ceiling on what an ``execve`` of a file bearing file
capabilities may place in the permitted set. What makes it inert here is
``no_new_privileges``, together with the absence of setuid binaries and file
capabilities in the image (stripped at build under J4). Two independent legs, and
the bounding set is not one of them, because clearing it needs CAP_SETPCAP which
the court refused.
"""

from __future__ import annotations

import ctypes
import os
import socket
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# capset(2), _LINUX_CAPABILITY_VERSION_3. The header struct is
#   struct __user_cap_header_struct { __u32 version; int pid; }
#   struct __user_cap_data_struct  { __u32 effective, permitted, inheritable; }[2]
# Two data blocks, because v3 covers capabilities 0..63.
_CAP_VERSION_3 = 0x20080522
_CAP_DATA_BLOCKS = 2

PROC_STATUS = Path("/proc/self/status")


class PrivilegeError(RuntimeError):
    """A process was not in the privilege state the boundary requires."""


@dataclass(frozen=True, slots=True)
class PrivilegeState:
    """What the kernel says about this process, not what we believe about it."""

    uid: int
    gid: int
    no_new_privs: bool
    cap_permitted: int
    cap_effective: int
    cap_inheritable: int
    cap_ambient: int

    @property
    def holds_no_capabilities(self) -> bool:
        return not (
            self.cap_permitted
            or self.cap_effective
            or self.cap_inheritable
            or self.cap_ambient
        )


class _CapHeader(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("pid", ctypes.c_int)]


class _CapData(ctypes.Structure):
    _fields_ = [
        ("effective", ctypes.c_uint32),
        ("permitted", ctypes.c_uint32),
        ("inheritable", ctypes.c_uint32),
    ]


def read_privilege_state(status_path: Path = PROC_STATUS) -> PrivilegeState:
    """Read this process's real privilege state out of ``/proc``.

    Deliberately reads the kernel's view rather than tracking what we called.
    A drop that silently failed, or a deployment that never dropped at all, is
    exactly the case the assertion exists to catch, so believing our own
    bookkeeping would defeat the point.
    """

    if type(status_path) is not type(Path("/")):
        raise TypeError("status_path must be an exact pathlib POSIX path")
    fields: dict[str, str] = {}
    for line in status_path.read_text(encoding="ascii", errors="replace").splitlines():
        name, separator, value = line.partition(":")
        if separator:
            fields[name.strip()] = value.strip()
    try:
        return PrivilegeState(
            uid=int(fields["Uid"].split()[0]),
            gid=int(fields["Gid"].split()[0]),
            no_new_privs=fields.get("NoNewPrivs", "0") == "1",
            cap_permitted=int(fields["CapPrm"], 16),
            cap_effective=int(fields["CapEff"], 16),
            cap_inheritable=int(fields["CapInh"], 16),
            # CapAmb predates none of our kernels, but treat absence as unknown-bad.
            cap_ambient=int(fields.get("CapAmb", "ffffffffffffffff"), 16),
        )
    except (KeyError, ValueError, IndexError) as error:
        raise PrivilegeError("could not read the process privilege state") from error


def assert_unprivileged(
    *, expected_uid: int | None = None, status_path: Path = PROC_STATUS
) -> PrivilegeState:
    """Fail closed unless this process is non-root and holds no capabilities (J5).

    Used in two places with the same meaning: the API process after it drops, and
    a spawned cell before it is handed any credential. ``no_new_privileges`` is
    required because it is one of the two legs that stop a dropped process
    regaining privilege through ``execve``.
    """

    state = read_privilege_state(status_path)
    if state.uid == 0:
        raise PrivilegeError("process must not run as root")
    if expected_uid is not None and state.uid != expected_uid:
        raise PrivilegeError(f"process runs as uid {state.uid}, expected {expected_uid}")
    if not state.holds_no_capabilities:
        raise PrivilegeError("process still holds capabilities")
    if not state.no_new_privs:
        raise PrivilegeError("process does not have no_new_privs set")
    return state


def clear_capability_sets() -> None:
    """Empty the permitted, effective and inheritable sets via ``capset(2)``.

    Honest about what this does: after a ``setuid`` away from uid 0 the kernel has
    ALREADY cleared these sets, so on the intended path this is belt and braces
    rather than the thing doing the work. It is kept because it makes the drop
    correct even when the caller was never uid 0, and because a silent no-op is
    cheaper than reasoning about which path a future caller took.
    """

    libc = ctypes.CDLL(None, use_errno=True)
    header = _CapHeader(version=_CAP_VERSION_3, pid=0)
    data = (_CapData * _CAP_DATA_BLOCKS)()
    if libc.capset(ctypes.byref(header), ctypes.byref(data)) != 0:
        raise PrivilegeError(
            f"capset failed: {os.strerror(ctypes.get_errno())}"
        )


def drop_privileges(uid: int, gid: int) -> PrivilegeState:
    """Drop to ``uid``/``gid`` permanently and verify the result from ``/proc``.

    Order matters and is not interchangeable: supplementary groups first, then
    ``setgid``, then ``setuid``. Dropping the uid first would remove the privilege
    needed to drop the groups, which is the classic way this is got wrong and
    leaves a process still in a group it should have shed.
    """

    if type(uid) is not int or type(gid) is not int or uid <= 0 or gid <= 0:
        raise PrivilegeError("drop target must be a non-root uid and gid")
    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)
    clear_capability_sets()
    # Never trust the calls; ask the kernel what actually happened.
    return assert_unprivileged(expected_uid=uid)


def assert_cell_process_unprivileged(pid: int, *, expected_uid: int | None = None) -> PrivilegeState:
    """Prove a SPAWNED CELL's privilege state before it is handed any credential.

    [2026] VJS-CC-VJS 7 J5. The reading is taken by the KERNEL from
    ``/proc/<pid>/status``, never from anything the cell says about itself: a cell
    that has been compromised is exactly the one that would report a clean state,
    so self-attestation would be worth nothing here.

    Checked immediately before issuance rather than at spawn, because the question
    is whether the process is unprivileged AT THE MOMENT it is trusted, and a spawn
    that succeeded some seconds ago proves nothing about now.
    """

    if type(pid) is not int or pid <= 1:
        raise PrivilegeError("cell privilege check needs a real pid")
    try:
        return assert_unprivileged(
            expected_uid=expected_uid, status_path=Path(f"/proc/{pid}/status")
        )
    except OSError as error:
        # A cell whose /proc we cannot read is a cell we cannot vouch for.
        raise PrivilegeError("cell privilege state is unreadable") from error


# The entrypoint writes the spawner socket's fd here before it drops the API. Its
# PRESENCE, validated as a live socket, is how the dropped API knows per-cell uids
# are in force - see per_cell_uid_mode_available.
SPAWNER_FD_ENV = "BOLTRIG_CELL_SPAWNER_FD"


def inherited_spawner_socket_fd(env: Mapping[str, str] | None = None) -> int | None:
    """The fd of a live inherited spawner socket, if the entrypoint handed one over.

    Validated as a real AF_UNIX/SOCK_STREAM socket rather than trusted as a bare
    env var, and validated WITHOUT taking ownership: a socket object built from the
    fd would close it on garbage collection, so the probe is detached. Returns the
    fd, or None if the value is absent, malformed, or not a live unix socket.
    """

    source = env if env is not None else os.environ
    raw = source.get(SPAWNER_FD_ENV)
    if not raw or not raw.isdigit():
        return None
    fd = int(raw)
    try:
        if not stat.S_ISSOCK(os.fstat(fd).st_mode):
            return None
    except OSError:
        return None
    probe = socket.socket(fileno=fd)
    try:
        live = probe.family == socket.AF_UNIX and probe.type == socket.SOCK_STREAM
    except OSError:
        live = False
    finally:
        probe.detach()  # never close the inherited fd
    return fd if live else None


def per_cell_uid_mode_available(
    status_path: Path = PROC_STATUS, env: Mapping[str, str] | None = None
) -> bool:
    """True where per-cell uids are actually in force, answered per vantage point.

    There are TWO honest vantage points and they cannot share one test, which is
    the correctness bug this function had:

    - The SPAWNER / entrypoint is uid 0 with the capability, so it answers from the
      kernel: uid 0 with a non-empty permitted set.
    - The API is DELIBERATELY dropped to a non-root uid with an empty permitted
      set, so it can never answer yes from its own /proc. It answers instead from
      the live spawner socket the entrypoint handed it. That fd is the transitive
      proof: the entrypoint forks a spawner ONLY after confirming its own uid-0
      capability, and the entrypoint is our own trusted code. The API trusting it
      is within the threat model - VJS-CC-VJS 5 is a hostile CELL reaching a
      sibling, not a hostile API, and the API is the party enforcing the boundary.

    It must still NEVER pretend: a bare env var is not enough, the fd is validated
    as a live unix socket, and a cell (which inherits neither the fd env nor uid 0)
    correctly reads False.
    """

    if inherited_spawner_socket_fd(env) is not None:
        return True
    try:
        state = read_privilege_state(status_path)
    except (PrivilegeError, OSError):
        # An absent or unreadable /proc is an UNPROVEN state, and an unproven
        # boundary must read as absent rather than propagate out of a predicate.
        return False
    return state.uid == 0 and bool(state.cap_permitted)


__all__ = [
    "PROC_STATUS",
    "SPAWNER_FD_ENV",
    "PrivilegeError",
    "PrivilegeState",
    "assert_cell_process_unprivileged",
    "assert_unprivileged",
    "clear_capability_sets",
    "drop_privileges",
    "inherited_spawner_socket_fd",
    "per_cell_uid_mode_available",
    "read_privilege_state",
]
