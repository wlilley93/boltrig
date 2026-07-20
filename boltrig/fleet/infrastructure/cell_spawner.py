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
import signal
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


ALLOWED_SIGNALS = (signal.SIGTERM, signal.SIGKILL)


def _reap_exited(live: dict[int, int]) -> None:
    """Clear any exited cells, so the spawner does not accumulate zombies."""

    while True:
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return  # no children at all
        if pid == 0:
            return  # children exist, none have exited
        live.pop(pid, None)


def _is_signal_request(payload: bytes) -> bool:
    try:
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(raw, dict) and raw.get("verb") == "signal"


def _serve_signal(sock: socket.socket, payload: bytes, live: dict[int, int]) -> None:
    """Signal a pid THIS spawner started, at the uid it started it with.

    The API names a pid and a signal. It does NOT name a uid: the spawner looks
    that up from its own record of what it spawned. Letting the caller choose the
    uid would turn a narrow supervisor verb into a general kill primitive over
    every uid in the cell band.
    """

    raw = json.loads(payload.decode("utf-8"))
    pid, number = raw.get("pid"), raw.get("signal")
    uid = live.get(pid) if type(pid) is int else None
    if uid is None or type(number) is not int:
        raise CellSpawnerError("signal request names a pid this spawner did not start")
    reap_cell(pid, uid, number)
    sock.sendmsg([json.dumps({"signalled": pid}).encode("utf-8")])


def reap_cell(pid: int, uid: int, number: int) -> None:
    """Signal a cell by forking a reaper that shares its uid.

    Found by testing rather than reasoning, and it changes the shape of this
    module: under the granted capability set NOTHING can signal a per-cell-uid
    cell directly. The API is a different uid and not the parent (EPERM, ECHILD),
    and the SPAWNER cannot either, because signalling across uids needs CAP_KILL
    and the grant is SETUID and SETGID only. Being uid 0 under ``cap_drop: ALL``
    is root in name and not in the one respect this needs.

    Same-uid signalling needs no capability, so the reaper drops to the cell's own
    uid and signals from there. It exists for one syscall and exits. The spawner
    stays the parent, so it still reaps normally.

    See docs/findings/2026-07-20-cell-lifecycle-under-per-cell-uids.md.
    """

    if type(pid) is not int or pid <= 1:
        raise CellSpawnerError("reap target must be a real pid")
    if not (MIN_CELL_UID <= uid <= MAX_CELL_UID):
        raise CellSpawnerError("reap uid is outside the cell band")
    if number not in ALLOWED_SIGNALS:
        # Only the two signals a supervisor legitimately needs. A general signal
        # verb would let a compromised API poke at anything the cell uid can reach.
        raise CellSpawnerError("only SIGTERM and SIGKILL may be delivered")
    reaper = os.fork()
    if reaper == 0:  # pragma: no cover - the child never returns to the caller
        try:
            os.setgid(uid)
            os.setuid(uid)
            os.kill(pid, number)
            os._exit(0)
        except BaseException:
            os._exit(1)
    _, status = os.waitpid(reaper, 0)
    if os.waitstatus_to_exitcode(status) != 0:
        raise CellSpawnerError("the same-uid reaper could not deliver the signal")


def serve_spawner(sock: socket.socket, policy: SpawnPolicy) -> None:
    """The privileged loop: read a request, validate it, spawn, hand back. Forever.

    Runs in the only process that keeps CAP_SETUID. It is deliberately a plain
    blocking loop with no framework, no plugins and no dynamic dispatch: this is
    the code that must be auditable by eye, because everything else in the stack
    depends on it refusing what the API asks for.

    A refused or malformed request never kills the loop. Killing it would take the
    whole lane down on one bad message from a process we already assume may be
    compromised, which converts a validation success into an outage.
    """

    # Only pids this spawner actually started may ever be signalled, and only at
    # the uid it started them with. The API names a pid; it does not get to say
    # whose uid to become, which would be a general kill primitive.
    live: dict[int, int] = {}
    while True:
        # Reap before blocking. The spawner is the cells' parent, so an exited
        # cell stays a ZOMBIE until someone waits for it, and a long-lived spawner
        # that never did would leak a pid-table entry per cell until the container
        # could fork no more. Opportunistic reaping here is enough because a cell
        # can only exit after a request created it, and every request passes here.
        _reap_exited(live)
        try:
            payload = sock.recv(_MAX_REQUEST_BYTES)
        except OSError:
            return
        if not payload:
            return  # the API closed; nothing left to serve
        try:
            if _is_signal_request(payload):
                _serve_signal(sock, payload, live)
                continue
            request = parse_spawn_request(payload, policy)
            pid, stdio = spawn_cell(request, policy)
            live[pid] = request.uid
        except (CellSpawnerError, OSError):
            # Fail closed and stay up. The API sees a result with no descriptors
            # and raises; it never mistakes a refusal for a running cell.
            try:
                sock.sendmsg([json.dumps({"error": "refused"}).encode("utf-8")])
            except OSError:
                return
            continue
        try:
            send_spawn_result(sock, pid, stdio)
        except OSError:
            return


__all__ = [
    "ALLOWED_SIGNALS",
    "MAX_CELL_UID",
    "MIN_CELL_UID",
    "CellSpawnerError",
    "SpawnPolicy",
    "SpawnRequest",
    "parse_spawn_request",
    "reap_cell",
    "receive_spawn_result",
    "serve_spawner",
    "send_spawn_result",
    "spawn_cell",
]
