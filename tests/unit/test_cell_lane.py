"""The per-cell lane refuses to pretend ([2026] VJS-CC-VJS 7 J1).

The lane's most important behaviour is not spawning. It is refusing to spawn when
per-cell uids are not actually available, because a cell that shares the API's uid
while every caller upstream believes it is isolated is worse than no cell: it is
the exact state VJS-CC-VJS 5 found to be a cross-tenant bearer disclosure, wearing
the costume of a fix.
"""

from __future__ import annotations

import socket
from typing import Any

import pytest

from boltrig.fleet.infrastructure import cell_lane as lane_module
from boltrig.fleet.infrastructure.cell_lane import CellLane
from boltrig.fleet.infrastructure.cell_slots import CellSlotAllocator
from boltrig.fleet.infrastructure.cell_spawner import CellSpawnerError


class _Binary:
    execution_path = "/opt/boltrig/codex/codex"

    def close(self) -> None:
        return None


async def test_the_lane_refuses_when_per_cell_uids_are_not_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never pretend. This is the whole point of the seam."""

    monkeypatch.setattr(lane_module, "per_cell_uid_mode_available", lambda: False)
    parent, child = socket.socketpair()
    try:
        lane = CellLane(parent, CellSlotAllocator(2))
        with pytest.raises(CellSpawnerError, match="not available"):
            await lane.spawn(
                binary=_Binary(),  # type: ignore[arg-type]
                arguments=("app-server",),
                cwd="/var/lib/boltrig/codex-cells/slot-0",
                environment={},
            )
    finally:
        parent.close()
        child.close()


async def test_a_failed_spawn_returns_the_slot_to_the_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A leaked slot would permanently shrink the number of cells the lane serves.

    Worse, it would do so silently: the lane would start refusing tenants with a
    "no free slot" error that has nothing to do with how many are actually live.
    """

    monkeypatch.setattr(lane_module, "per_cell_uid_mode_available", lambda: True)

    async def explode(*_args: Any, **_kwargs: Any) -> None:
        raise CellSpawnerError("spawner said no")

    monkeypatch.setattr(CellLane, "_request", explode)
    parent, child = socket.socketpair()
    try:
        allocator = CellSlotAllocator(1)
        lane = CellLane(parent, allocator)
        with pytest.raises(CellSpawnerError, match="spawner said no"):
            await lane.spawn(
                binary=_Binary(),  # type: ignore[arg-type]
                arguments=("app-server",),
                cwd="/var/lib/boltrig/codex-cells/slot-0",
                environment={},
            )
        assert allocator.held_uids() == frozenset()
        allocator.acquire()  # the slot is genuinely reusable, not just untracked
    finally:
        parent.close()
        child.close()


def test_the_lane_demands_a_real_allocator() -> None:
    parent, child = socket.socketpair()
    try:
        with pytest.raises(CellSpawnerError):
            CellLane(parent, object())  # type: ignore[arg-type]
    finally:
        parent.close()
        child.close()
