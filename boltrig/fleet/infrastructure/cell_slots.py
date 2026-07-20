"""Per-cell uid slots ([2026] VJS-CC-VJS 7 J2 and J10).

The court REFUSED ``CAP_CHOWN`` and said why: it is not necessary. H6 had offered
"CAP_CHOWN or the layout that avoids it" and the layout does avoid it. A tmpfs
declared in compose with ``uid=``, ``gid=`` and ``mode=0700`` is created by the
KERNEL already owned by that uid, so nothing is ever given away and nothing needs
chowning. A forked child that has already dropped to the cell uid can populate its
own slot, and is refused ``EACCES`` on any sibling's.

So a slot is a static triple: an index, the uid the compose mount was declared
with, and the root that mount appears at. This module does not create the mounts;
compose does, at container start, which is the entire point. What it does is hand
them out, and refuse to hand the same one to two live cells.

J10 requires uids that are actually distinct and NEVER reused between concurrent
cells. Reuse across TIME is fine and unavoidable (a slot returns to the pool when
its cell dies); reuse at the same INSTANT would mean two cells sharing a uid, which
is precisely the state the whole grant exists to end. The allocator therefore
refuses rather than blocks: a lane that quietly queued would look like it was
serving both tenants while one waited, and a refusal the caller can see is better
than a stall it cannot.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from boltrig.fleet.infrastructure.cell_spawner import MAX_CELL_UID, MIN_CELL_UID

# The mount point compose declares each slot at. Kept here so the code and the
# compose file cannot drift silently; a test holds them in step.
CELL_SLOT_ROOT = Path("/var/lib/boltrig/codex-cells")
# uid for slot N. Deliberately dense and predictable: the uid is not a secret, it
# is a kernel-enforced separator, and a readable mapping is easier to audit.
FIRST_SLOT_UID = 20001
# The number of per-cell slots declared as tmpfs mounts in docker-compose. The
# allocator and the compose file must agree; test_cell_slots holds them in step.
DECLARED_CELL_SLOTS = 4


class CellSlotError(RuntimeError):
    """A cell slot could not be allocated, released, or trusted."""


@dataclass(frozen=True, slots=True)
class CellSlot:
    """One statically declared per-cell uid and the tree that belongs to it."""

    index: int
    uid: int
    gid: int
    root: Path

    def __post_init__(self) -> None:
        if type(self.index) is not int or self.index < 0:
            raise CellSlotError("cell slot index must be a non-negative int")
        if not (MIN_CELL_UID <= self.uid <= MAX_CELL_UID):
            raise CellSlotError("cell slot uid is outside the reserved band")
        if self.uid != self.gid:
            raise CellSlotError("cell slot uid and gid must match the compose mount")
        if type(self.root) is not type(Path("/")) or not self.root.is_absolute():
            raise CellSlotError("cell slot root must be an absolute path")


def slot_for_index(index: int, *, root: Path = CELL_SLOT_ROOT) -> CellSlot:
    """The slot compose declared at ``index``. Pure: it touches no filesystem."""

    if type(index) is not int or index < 0:
        raise CellSlotError("cell slot index must be a non-negative int")
    uid = FIRST_SLOT_UID + index
    if uid > MAX_CELL_UID:
        raise CellSlotError("cell slot index exceeds the reserved uid band")
    return CellSlot(index=index, uid=uid, gid=uid, root=root / f"slot-{index}")


class CellSlotAllocator:
    """Hand out per-cell slots, and never the same one to two live cells.

    Thread-safe by a plain lock rather than an async one: the caller is an asyncio
    provider, but allocation is a few microseconds of bookkeeping and a lock that
    also works from a thread is one fewer thing to reason about at a boundary that
    must not go wrong.
    """

    __slots__ = ("_held", "_lock", "_slots")

    def __init__(self, capacity: int, *, root: Path = CELL_SLOT_ROOT) -> None:
        if type(capacity) is not int or capacity < 1:
            raise CellSlotError("cell slot capacity must be a positive int")
        self._slots = tuple(slot_for_index(index, root=root) for index in range(capacity))
        self._held: set[int] = set()
        self._lock = threading.Lock()

    @property
    def capacity(self) -> int:
        return len(self._slots)

    def acquire(self) -> CellSlot:
        """Take a free slot, or refuse. Never returns one already held."""

        with self._lock:
            for slot in self._slots:
                if slot.index not in self._held:
                    self._held.add(slot.index)
                    return slot
        raise CellSlotError("no free cell slot: every declared uid is in use")

    def release(self, slot: CellSlot) -> None:
        """Return a slot to the pool.

        Releasing a slot that is not held is an ERROR, not a no-op. A double
        release would put a live cell's uid back in the pool and hand it to a
        second cell, which is exactly the concurrent reuse J10 forbids, so it must
        be loud rather than forgiving.
        """

        if type(slot) is not CellSlot:
            raise CellSlotError("release requires an exact CellSlot")
        with self._lock:
            if slot.index not in self._held:
                raise CellSlotError("cell slot was not held")
            self._held.discard(slot.index)

    def held_uids(self) -> frozenset[int]:
        """The uids currently in use, for the J10 startup and runtime assertions."""

        with self._lock:
            return frozenset(
                self._slots[index].uid for index in self._held if index < len(self._slots)
            )


def assert_slots_are_distinct(slots: tuple[CellSlot, ...]) -> None:
    """J10: prove the uids really are distinct rather than assuming the mapping.

    The mapping is generated, so this cannot fail today. It is here because a
    future change to the layout (a shared slot, an off-by-one, a re-used index)
    would otherwise reintroduce the shared-uid state silently, and silence is the
    failure mode this whole program has been correcting.
    """

    if type(slots) is not tuple or not slots:
        raise CellSlotError("slot assertion requires a non-empty tuple")
    uids = [slot.uid for slot in slots]
    roots = [slot.root for slot in slots]
    if len(set(uids)) != len(uids):
        raise CellSlotError("cell slot uids are not distinct")
    if len(set(roots)) != len(roots):
        raise CellSlotError("cell slot roots are not distinct")
    if any(uid == 0 for uid in uids):
        raise CellSlotError("a cell slot claims uid 0")


__all__ = [
    "CELL_SLOT_ROOT",
    "DECLARED_CELL_SLOTS",
    "FIRST_SLOT_UID",
    "CellSlot",
    "CellSlotAllocator",
    "CellSlotError",
    "assert_slots_are_distinct",
    "slot_for_index",
]
