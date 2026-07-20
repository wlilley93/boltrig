"""The minimal privileged spawner for per-cell uids ([2026] VJS-CC-VJS 7 J3).

This is the ONLY thing in the stack permitted to keep CAP_SETUID/CAP_SETGID, and
it exists because the alternative is forbidden: ``CodexCellSupervisor._spawn`` is
an in-process asyncio spawn inside the uvicorn API process, so a plain ``user: 0``
would make the whole API root, including the paths that read model output.

THE DESIGN RULE, and everything here follows from it: **the spawner validates, it
does not obey.** The API is the process that parses untrusted model output, so it
is the process most likely to be compromised, and it is on the other end of this
socket. A spawner that executed whatever argv it was handed, as whatever uid it
was handed, would simply relocate root into the API's gift. So every field is
checked against policy the spawner holds itself:

- the uid must be inside the reserved per-cell band, never 0, never the API's own;
- ``argv[0]`` must be the exact pinned Codex binary path, not merely absolute;
- the working directory must be inside the cell stack root;
- the environment is rebuilt from the request's cell values, not passed through.

TRANSPORT: a ``socketpair`` created BEFORE the privilege drop. That choice is
deliberate. A filesystem socket would need a path (squattable, as the ingress
socket was) and an authentication story; an inherited socketpair has neither,
because the only process holding the other end is the child we forked, and no
later process can obtain one. The cell's stdio comes back over the same socket as
file descriptors via ``SCM_RIGHTS``, so the API drives the cell normally while
never having been privileged.

``production_ready`` stays False and this module enacts nothing on its own: it is
only reachable where the capability was actually granted, which
``per_cell_uid_mode_available`` reports from the kernel.
"""

from __future__ import annotations

import array
import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path

from boltrig.fleet.infrastructure.cell_privilege import drop_privileges

# The reserved per-cell uid band. Chosen well above the API's 10001 and far from
# anything Debian allocates, so a cell uid can never collide with a system account
# or with the API itself. J10 additionally forbids reuse between concurrent cells.
MIN_CELL_UID = 20000
MAX_CELL_UID = 29999
_MAX_REQUEST_BYTES = 64 * 1024
_STDIO_COUNT = 3


class CellSpawnerError(RuntimeError):
    """A spawn request was refused, or the spawner could not serve it."""


@dataclass(frozen=True, slots=True)
class SpawnPolicy:
    """What this spawner will agree to do, held by the spawner and not the caller.

    Passed in at construction, before the API is ever spoken to, so a compromised
    API cannot widen it.
    """

    binary: Path
    stack_root: Path

    def __post_init__(self) -> None:
        for value in (self.binary, self.stack_root):
            if type(value) is not type(Path("/")) or not value.is_absolute():
                raise CellSpawnerError("spawn policy paths must be absolute")


@dataclass(frozen=True, slots=True)
class SpawnRequest:
    """One validated request to start a cell under its own uid."""

    uid: int
    gid: int
    argv: tuple[str, ...]
    cwd: str
    env: dict[str, str]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CellSpawnerError(message)


def parse_spawn_request(payload: bytes, policy: SpawnPolicy) -> SpawnRequest:
    """Validate a request against policy the SPAWNER holds. Fail closed.

    Every check here assumes the sender is hostile, because the sender is the
    process that reads model output. None of these are formalities.
    """

    _require(type(payload) is bytes, "spawn request must be bytes")
    _require(0 < len(payload) <= _MAX_REQUEST_BYTES, "spawn request size is not sane")
    try:
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CellSpawnerError("spawn request is not parseable JSON") from error
    _require(isinstance(raw, dict), "spawn request must be an object")

    uid, gid = raw.get("uid"), raw.get("gid")
    _require(type(uid) is int and type(gid) is int, "spawn uid and gid must be ints")
    # Never uid 0, and never the API's own uid: a cell that shared either would
    # have no boundary at all, which is the whole point of the grant.
    _require(MIN_CELL_UID <= uid <= MAX_CELL_UID, "spawn uid is outside the cell band")
    _require(MIN_CELL_UID <= gid <= MAX_CELL_UID, "spawn gid is outside the cell band")

    argv = raw.get("argv")
    _require(
        isinstance(argv, list) and argv and all(type(item) is str for item in argv),
        "spawn argv must be a non-empty list of strings",
    )
    # The EXACT pinned binary, not merely an absolute path: "absolute" would still
    # let a compromised API name any program on the image.
    _require(argv[0] == policy.binary.as_posix(), "spawn argv[0] is not the pinned binary")

    cwd = raw.get("cwd")
    _require(type(cwd) is str and cwd, "spawn cwd must be a non-empty string")
    resolved = Path(cwd)
    _require(resolved.is_absolute(), "spawn cwd must be absolute")
    # ``is_relative_to`` is LEXICAL, so "<stack>/../other" is "inside" the stack
    # root as far as it is concerned. That is the same escape as the "/v1/../admin"
    # proxy bug, and it is refused the same way: by demanding the path already be
    # normalized rather than by normalizing it for the caller. Resolving would also
    # follow symlinks, which a cell uid can create inside its own tree.
    _require(".." not in resolved.parts, "spawn cwd must not traverse upwards")
    _require(
        os.path.normpath(cwd) == cwd.rstrip("/") or cwd == "/",
        "spawn cwd must be a normalized path",
    )
    _require(
        resolved == policy.stack_root or resolved.is_relative_to(policy.stack_root),
        "spawn cwd must live inside the cell stack root",
    )

    env = raw.get("env")
    _require(
        isinstance(env, dict)
        and all(type(k) is str and type(v) is str for k, v in env.items()),
        "spawn env must be a string mapping",
    )
    return SpawnRequest(uid, gid, tuple(argv), cwd, dict(env))


def _exec_cell(request: SpawnRequest, stdio: tuple[int, int, int]) -> None:
    """In the forked child: drop to the cell uid, wire stdio, exec. Never returns."""

    os.dup2(stdio[0], 0)
    os.dup2(stdio[1], 1)
    os.dup2(stdio[2], 2)
    # The drop must happen BEFORE exec so the cell never runs privileged for an
    # instant, and drop_privileges re-reads /proc to prove it rather than assuming.
    drop_privileges(request.uid, request.gid)
    os.execve(request.argv[0], list(request.argv), request.env)


def spawn_cell(request: SpawnRequest, policy: SpawnPolicy) -> tuple[int, tuple[int, int, int]]:
    """Fork a cell under its own uid and return its pid and the parent stdio ends.

    The caller keeps the parent ends of three pipes; the child gets the other ends
    as its stdin, stdout and stderr. On any failure the child is not left running:
    an exec that fails exits the child immediately with a distinct status.
    """

    if type(request) is not SpawnRequest or type(policy) is not SpawnPolicy:
        raise CellSpawnerError("spawn requires an exact request and policy")
    stdin_r, stdin_w = os.pipe()
    stdout_r, stdout_w = os.pipe()
    stderr_r, stderr_w = os.pipe()
    child_ends = (stdin_r, stdout_w, stderr_w)
    parent_ends = (stdin_w, stdout_r, stderr_r)
    pid = os.fork()
    if pid == 0:  # pragma: no cover - the child never returns to the test process
        try:
            for descriptor in parent_ends:
                os.close(descriptor)
            _exec_cell(request, child_ends)
        except BaseException:
            os._exit(127)
    for descriptor in child_ends:
        os.close(descriptor)
    return pid, parent_ends


def send_spawn_result(sock: socket.socket, pid: int, stdio: tuple[int, int, int]) -> None:
    """Hand the pid and the three stdio descriptors back over the socketpair.

    ``SCM_RIGHTS`` is what lets the API drive a process it was never privileged
    enough to create. The descriptors are closed here afterwards: the API owns
    them now, and a spawner holding a live handle on every cell's stdio would be a
    needless accumulation of reach in the one process that keeps capabilities.
    """

    descriptors = array.array("i", stdio)
    sock.sendmsg(
        [json.dumps({"pid": pid}).encode("utf-8")],
        [(socket.SOL_SOCKET, socket.SCM_RIGHTS, descriptors)],
    )
    for descriptor in stdio:
        os.close(descriptor)


def receive_spawn_result(sock: socket.socket) -> tuple[int, tuple[int, int, int]]:
    """The API side of :func:`send_spawn_result`."""

    descriptors = array.array("i")
    payload, ancillary, _flags, _addr = sock.recvmsg(
        _MAX_REQUEST_BYTES, socket.CMSG_SPACE(_STDIO_COUNT * descriptors.itemsize)
    )
    for level, kind, data in ancillary:
        if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
            descriptors.frombytes(data[: len(data) - (len(data) % descriptors.itemsize)])
    if len(descriptors) != _STDIO_COUNT:
        raise CellSpawnerError("spawn result did not carry the cell stdio")
    try:
        pid = json.loads(payload.decode("utf-8"))["pid"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise CellSpawnerError("spawn result is not a readable pid") from error
    if type(pid) is not int or pid <= 0:
        raise CellSpawnerError("spawn result pid is not a live pid")
    return pid, (descriptors[0], descriptors[1], descriptors[2])


__all__ = [
    "MAX_CELL_UID",
    "MIN_CELL_UID",
    "CellSpawnerError",
    "SpawnPolicy",
    "SpawnRequest",
    "parse_spawn_request",
    "receive_spawn_result",
    "send_spawn_result",
    "spawn_cell",
]
