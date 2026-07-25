"""Drive a spawner-created cell from the unprivileged API ([2026] VJS-CC-VJS 7 J1).

``CodexCellSupervisor`` expects a ``ManagedCodexProcess``: a pid, three streams,
and terminate/kill/wait. A cell created by the privileged spawner satisfies none
of that for free, because it is not the API's child and does not share its uid.
This adapter supplies it, and the shape is dictated by what the kernel actually
permits, which was measured rather than assumed
(``docs/findings/2026-07-20-cell-lifecycle-under-per-cell-uids.md``):

- **stdio** arrives as descriptors over ``SCM_RIGHTS`` and is wrapped in ordinary
  asyncio streams. This part is free.
- **terminate and kill** must go BACK through the spawner. The API cannot signal
  the cell (EPERM, different uid) and neither can the spawner directly (no
  CAP_KILL); the spawner forks a same-uid reaper. So these verbs are requests,
  not syscalls.
- **wait** uses ``pidfd_open``, which the API CAN do on a foreign-uid process even
  though it cannot signal one. That matters: exit is observed without a round
  trip, so a busy or wedged spawner cannot starve the supervisor of the one fact
  it most needs.

``returncode`` is deliberately best-effort. The API is not the parent, so it never
sees a wait status and cannot report the exit CODE. It can report that the process
is gone, which is what the transport actually branches on. Reporting a fabricated
0 would be worse than reporting None.
"""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Callable

from boltrig.fleet.infrastructure.codex_stdio_transport import (
    EXIT_STATUS_UNKNOWN,
    CodexStdin,
)
from boltrig.fleet.infrastructure.cell_spawner import (
    ALLOWED_SIGNALS,
    CellSpawnerError,
)

# One definition of "exited, status unknown", shared with the transport that
# has to decide whether a teardown is worth a warning.
_EXITED = EXIT_STATUS_UNKNOWN


class SpawnedCellProcess:
    """A ``ManagedCodexProcess`` over a cell the privileged spawner created."""

    __slots__ = ("_closed", "_pidfd", "_returncode", "_signaller", "pid", "stderr", "stdin", "stdout")

    # Declared with the protocol's own optional types rather than the narrower
    # concrete ones. ManagedCodexProcess attributes are invariant, so a stricter
    # annotation here would make this class fail to satisfy the very protocol the
    # supervisor consumes it through.
    pid: int
    stdin: CodexStdin | None
    stdout: asyncio.StreamReader | None
    stderr: asyncio.StreamReader | None

    def __init__(
        self,
        *,
        pid: int,
        stdin: asyncio.StreamWriter,
        stdout: asyncio.StreamReader,
        stderr: asyncio.StreamReader,
        signaller: Callable[[int, signal.Signals], None],
        pidfd: int,
    ) -> None:
        self.pid = pid
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self._signaller = signaller
        self._pidfd = pidfd
        self._returncode: int | None = None
        self._closed = False

    @property
    def returncode(self) -> int | None:
        """Best effort, and honest about it: None until the cell is observed gone.

        The API is not the parent, so no wait status ever reaches it and the true
        exit code is not knowable here. Returning a fabricated 0 would let a
        crashed cell read as a clean one, so absence is reported as absence.
        """

        return self._returncode

    async def wait(self) -> int:
        """Block until the cell exits, using the pidfd rather than the spawner.

        Once exit is observed the pidfd has served its only purpose, so it is
        closed here: the lane's teardown paths all converge on ``wait`` and a
        handle nobody closes otherwise leaks one fd per adopted cell.
        """

        if self._returncode is not None:
            return self._returncode
        loop = asyncio.get_running_loop()
        waiter = loop.create_future()
        loop.add_reader(self._pidfd, lambda: _resolve(waiter))
        try:
            await waiter
        finally:
            loop.remove_reader(self._pidfd)
        self._returncode = _EXITED
        self.close()
        return _EXITED

    def terminate(self) -> None:
        self._signal(signal.SIGTERM)

    def kill(self) -> None:
        self._signal(signal.SIGKILL)

    def _signal(self, number: signal.Signals) -> None:
        """Ask the spawner to signal the cell; the API cannot do it itself.

        The request goes through the lane's signaller, which serialises it with
        provision/spawn under the lane lock and drains the spawner's
        ``{'signalled': pid}`` reply - an unread reply would be consumed as the
        answer to the NEXT lane request and desync the protocol, and an
        unlocked send could interleave with an in-flight spawn's bytes.
        """

        if self._closed or number not in ALLOWED_SIGNALS:
            return
        self._signaller(self.pid, number)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            os.close(self._pidfd)
        except OSError:
            pass


def _resolve(waiter: asyncio.Future[None]) -> None:
    if not waiter.done():
        waiter.set_result(None)


async def adopt_spawned_cell(
    *, pid: int, stdio: tuple[int, int, int], signaller: Callable[[int, signal.Signals], None]
) -> SpawnedCellProcess:
    """Wrap a spawner-created cell in the process surface the supervisor expects.

    ``pidfd_open`` is taken FIRST, before any stream is wired. The pid is not the
    API's child, so it could in principle be reaped and reused by the spawner
    between the spawn and the adopt; taking the pidfd first pins the identity to
    the process that actually exists now rather than to a number.
    """

    if type(pid) is not int or pid <= 1:
        raise CellSpawnerError("cannot adopt a cell without a real pid")
    try:
        pidfd = os.pidfd_open(pid)
    except OSError as error:
        raise CellSpawnerError("the spawned cell was gone before it was adopted") from error
    loop = asyncio.get_running_loop()
    stdin_transport, stdin_protocol = await loop.connect_write_pipe(
        asyncio.streams.FlowControlMixin, os.fdopen(stdio[0], "wb", buffering=0)
    )
    writer = asyncio.StreamWriter(stdin_transport, stdin_protocol, None, loop)
    return SpawnedCellProcess(
        pid=pid,
        stdin=writer,
        stdout=await _reader(loop, stdio[1]),
        stderr=await _reader(loop, stdio[2]),
        signaller=signaller,
        pidfd=pidfd,
    )


async def _reader(loop: asyncio.AbstractEventLoop, descriptor: int) -> asyncio.StreamReader:
    reader = asyncio.StreamReader(loop=loop)
    await loop.connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader, loop=loop),
        os.fdopen(descriptor, "rb", buffering=0),
    )
    return reader


__all__ = ["SpawnedCellProcess", "adopt_spawned_cell"]
