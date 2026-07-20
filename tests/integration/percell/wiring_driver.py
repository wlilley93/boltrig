"""Prove the PRODUCT path, not the harness ([2026] VJS-CC-VJS 7 J1 wiring).

Runs inside the built image. The entrypoint forks a spawner and hands the API a
socket, then DROPS the API to uid 10001, exactly as scripts/kernel-entrypoint.py
does before exec'ing uvicorn. The dropped API must then see per-cell mode from the
inherited socket, build a CellLane, and route a real spawn through it. This is the
exact join the enactment was missing and that every green test hid.
"""
import asyncio
import os
import socket
import sys
from pathlib import Path

from boltrig.fleet.infrastructure import cell_privilege as cp
from boltrig.fleet.infrastructure.cell_lane import CellLane
from boltrig.fleet.infrastructure.cell_slots import CellSlotAllocator
from boltrig.fleet.infrastructure.cell_spawner import SpawnPolicy, serve_spawner

parent, child = socket.socketpair()
if os.fork() == 0:
    parent.close()
    serve_spawner(child, SpawnPolicy(binary=Path("/bin/echo"), stack_root=Path("/tmp")))
    os._exit(0)
child.close()
os.set_inheritable(parent.fileno(), True)
os.environ[cp.SPAWNER_FD_ENV] = str(parent.fileno())

pid = os.fork()
if pid == 0:
    cp.drop_privileges(10001, 10001)  # become the API

    class _Binary:
        execution_path = "/bin/echo"

        def close(self) -> None:
            return None

    async def main() -> None:
        print("dropped API uid:", os.getuid(),
              "| per_cell_uid_mode_available:", cp.per_cell_uid_mode_available())
        fd = cp.inherited_spawner_socket_fd(os.environ)
        lane = CellLane(socket.socket(fileno=os.dup(fd)), CellSlotAllocator(4))
        proc = await lane.spawn(
            binary=_Binary(), arguments=("routed-through-the-lane",), cwd="/tmp", environment={}
        )
        out = await proc.stdout.read(64)
        print("lane spawned cell pid:", proc.pid, "| stdout:", out.decode().strip())
        proc.close()

    asyncio.run(main())
    sys.stdout.flush()
    os._exit(0)
os.waitpid(pid, 0)
