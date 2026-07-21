"""The per-cell uid lane: one seam the supervisor talks to ([2026] VJS-CC-VJS 7 J1).

The supervisor should not know about socketpairs, `SCM_RIGHTS`, uid bands or slot
allocation. It knows it wants a process. This is the one object that turns that
want into a request to the privileged spawner, and it exists so the change to
``CodexCellSupervisor`` is a single branch rather than a rewrite.

Two properties are deliberate.

**The lane re-checks the kernel, it does not trust its own existence.** Being
constructed is not evidence that per-cell uids are available; a composition root
could build one on a box where the capability was never granted. So ``spawn``
asks ``per_cell_uid_mode_available`` and refuses rather than silently producing a
cell that shares the API's uid while everything upstream believes it is isolated.
Believing otherwise is the exact failure [2026] VJS-CC-VJS 5 found.

**A slot is held for the cell's whole life and released once.** The slot IS the
isolation; releasing it early would let a second cell take a uid that is still in
use, which J10 forbids. The lane therefore ties the release to the process exiting
rather than to the caller remembering.
"""

from __future__ import annotations

import asyncio
import json
import socket

from boltrig.fleet.infrastructure.cell_privilege import per_cell_uid_mode_available
from boltrig.fleet.infrastructure.cell_process import (
    SpawnedCellProcess,
    adopt_spawned_cell,
)
from boltrig.fleet.infrastructure.cell_slots import CellSlot, CellSlotAllocator
from boltrig.fleet.infrastructure.cell_spawner import (
    CellSpawnerError,
    receive_spawn_result,
)
from boltrig.fleet.infrastructure.codex_cell_policy import PinnedCodexBinary


class CellLane:
    """Spawn cells under per-cell uids through the privileged spawner."""

    __slots__ = ("_allocator", "_lock", "_sock")

    def __init__(self, spawner: socket.socket, allocator: CellSlotAllocator) -> None:
        if type(allocator) is not CellSlotAllocator:
            raise CellSpawnerError("cell lane requires an exact allocator")
        self._sock = spawner
        self._allocator = allocator
        # The spawner socket carries one request and one reply at a time; two
        # concurrent spawns would interleave and each could adopt the other's
        # descriptors. Serialising here is what makes concurrency safe upstream.
        self._lock = asyncio.Lock()

    def acquire_slot(self) -> CellSlot:
        """Reserve a distinct per-cell uid slot, or refuse.

        The kernel re-check lives here (not in ``spawn``) because acquisition is now
        the first step the provider takes; refusing here, before any admission or
        bearer work, is the same "never pretend" rule the lane was built on. A cell
        sharing the API's uid while callers believe it is isolated is worse than no
        cell at all ([2026] VJS-CC-VJS 5).
        """

        if not per_cell_uid_mode_available():
            raise CellSpawnerError("per-cell uid mode is not available on this host")
        return self._allocator.acquire()

    def release_slot(self, slot: CellSlot) -> None:
        """Return a slot to the pool. Release ownership sits with the provider,
        which ties it to the cell's observed exit (J10: a uid is never reused while
        its cell is still live)."""

        self._allocator.release(slot)

    async def provision(
        self,
        slot: CellSlot,
        *,
        dirs: list[dict[str, object]],
        files: list[dict[str, object]],
    ) -> None:
        """Have the spawner build this cell's own tree + files, AS the cell uid.

        The API cannot write the kernel-owned 0700 slot, so it hands the spawner a
        directory/file manifest; the spawner forks a child that setuids to this
        cell's uid and creates them inside the cell's own slot (paths the spawner
        re-binds to that uid). Refusal raises, exactly like a spawn refusal.
        """

        payload = json.dumps(
            {
                "verb": "provision",
                "uid": slot.uid,
                "gid": slot.gid,
                "root": slot.root.as_posix(),
                "dirs": dirs,
                "files": files,
            }
        ).encode("utf-8")
        async with self._lock:
            await asyncio.to_thread(self._sock.sendall, payload)
            reply = await asyncio.to_thread(self._sock.recv, 4096)
        try:
            parsed = json.loads(reply.decode("utf-8")) if reply else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CellSpawnerError("provision reply was not readable") from error
        if not (isinstance(parsed, dict) and parsed.get("provisioned") is True):
            raise CellSpawnerError("cell provisioning was refused")

    async def spawn(
        self,
        slot: CellSlot,
        *,
        binary: PinnedCodexBinary,
        arguments: tuple[str, ...],
        cwd: str,
        environment: dict[str, str],
    ) -> SpawnedCellProcess:
        """Ask the spawner for a cell under the given (already-acquired) slot's uid.

        The slot is acquired by the provider via :meth:`acquire_slot` and released by
        the provider when the cell exits, so this method neither allocates nor frees:
        it turns a slot into a running, adopted process.
        """

        return await self._request(slot, binary, arguments, cwd, environment)

    async def _request(
        self,
        slot: CellSlot,
        binary: PinnedCodexBinary,
        arguments: tuple[str, ...],
        cwd: str,
        environment: dict[str, str],
    ) -> SpawnedCellProcess:
        # argv[0] is the binary's REAL path, not its execution_path. execution_path
        # is ``/proc/self/fd/<n>`` in the API's own fd table (for a TOCTOU-safe
        # fexecve on the in-process path), but the spawner is a SEPARATE process:
        # that fd number means nothing across the process boundary, and the spawner
        # execs by path and pins argv[0] to its policy binary. Path-exec is sound
        # here because the binary lives at a fixed, root-owned, world-executable path
        # on a read-only rootfs the cell uid cannot rewrite, so it cannot be swapped
        # between the supervisor's sha256 verify and the spawner's execve.
        payload = json.dumps(
            {
                "uid": slot.uid,
                "gid": slot.gid,
                "argv": [binary.path.as_posix(), *arguments],
                "cwd": cwd,
                "env": environment,
            }
        ).encode("utf-8")
        async with self._lock:
            await asyncio.to_thread(self._sock.sendall, payload)
            pid, stdio = await asyncio.to_thread(receive_spawn_result, self._sock)
        return await adopt_spawned_cell(pid=pid, stdio=stdio, spawner=self._sock)


__all__ = ["CellLane"]
