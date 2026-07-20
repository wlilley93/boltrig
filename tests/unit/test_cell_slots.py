"""Per-cell uid slots: distinct, and never concurrently reused (VJS-CC-VJS 7 J2/J10).

The property under test is narrow and load-bearing: two live cells must never hold
the same uid. Reuse across time is fine and unavoidable. Reuse at the same instant
is the shared-uid state that [2026] VJS-CC-VJS 5 found to be a cross-tenant bearer
disclosure, so the allocator must make it unrepresentable rather than unlikely.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boltrig.fleet.infrastructure.cell_slots import (
    FIRST_SLOT_UID,
    CellSlot,
    CellSlotAllocator,
    CellSlotError,
    assert_slots_are_distinct,
    slot_for_index,
)


@pytest.mark.unit
def test_a_slot_maps_to_its_own_uid_and_its_own_tree() -> None:
    first, second = slot_for_index(0), slot_for_index(1)
    assert first.uid == FIRST_SLOT_UID
    assert second.uid == FIRST_SLOT_UID + 1
    assert first.root != second.root
    assert first.uid == first.gid  # must match how compose declared the mount


@pytest.mark.unit
def test_two_live_cells_can_never_hold_the_same_slot() -> None:
    allocator = CellSlotAllocator(2)
    a, b = allocator.acquire(), allocator.acquire()
    assert a.uid != b.uid
    assert allocator.held_uids() == frozenset({a.uid, b.uid})
    # Exhausted: refuse rather than hand out a uid that is already live.
    with pytest.raises(CellSlotError, match="no free cell slot"):
        allocator.acquire()


@pytest.mark.unit
def test_a_released_slot_returns_to_the_pool() -> None:
    allocator = CellSlotAllocator(1)
    first = allocator.acquire()
    allocator.release(first)
    assert allocator.held_uids() == frozenset()
    again = allocator.acquire()
    assert again.uid == first.uid  # reuse across TIME is fine


@pytest.mark.unit
def test_a_double_release_is_an_error_not_a_no_op() -> None:
    """A forgiving double release would hand a LIVE cell's uid to a second cell.

    That is the concurrent reuse J10 forbids, so it is loud rather than tolerant.
    """

    allocator = CellSlotAllocator(2)
    slot = allocator.acquire()
    allocator.release(slot)
    with pytest.raises(CellSlotError, match="not held"):
        allocator.release(slot)


@pytest.mark.unit
def test_releasing_a_slot_that_was_never_held_is_refused() -> None:
    allocator = CellSlotAllocator(2)
    with pytest.raises(CellSlotError, match="not held"):
        allocator.release(slot_for_index(1))


@pytest.mark.unit
def test_the_distinctness_assertion_catches_a_broken_layout() -> None:
    """The mapping is generated so this cannot fail today; that is not the point.

    A future layout change (a shared slot, an off-by-one, a reused index) would
    otherwise reintroduce the shared-uid state in silence.
    """

    good = tuple(slot_for_index(index) for index in range(3))
    assert_slots_are_distinct(good)

    duplicate = (slot_for_index(0), slot_for_index(0))
    with pytest.raises(CellSlotError, match="distinct"):
        assert_slots_are_distinct(duplicate)

    shared_root = (
        CellSlot(index=0, uid=20001, gid=20001, root=Path("/same")),
        CellSlot(index=1, uid=20002, gid=20002, root=Path("/same")),
    )
    with pytest.raises(CellSlotError, match="roots are not distinct"):
        assert_slots_are_distinct(shared_root)


@pytest.mark.unit
@pytest.mark.parametrize(
    "kwargs",
    [
        {"uid": 0, "gid": 0},  # root, the one uid a cell may never hold
        {"uid": 10001, "gid": 10001},  # the API's own uid
        {"uid": 20001, "gid": 20002},  # uid and gid disagree with the mount
        {"uid": 99999, "gid": 99999},  # outside the reserved band
    ],
)
def test_a_slot_outside_the_reserved_band_is_refused(kwargs: dict[str, int]) -> None:
    with pytest.raises(CellSlotError):
        CellSlot(index=0, root=Path("/var/lib/boltrig/codex-cells/slot-0"), **kwargs)


@pytest.mark.unit
def test_the_band_bounds_the_number_of_slots() -> None:
    """Running out of reserved uids must be an error, not a wrap into system uids."""

    with pytest.raises(CellSlotError, match="band"):
        slot_for_index(100_000)


@pytest.mark.unit
def test_the_declared_compose_mounts_match_the_slot_mapping() -> None:
    """The kernel creates these trees; the code hands them out. They must agree.

    A mismatch would be silent and severe: the allocator would hand a cell a uid
    whose tree is owned by someone else, and the cell would be refused EACCES on
    its own workspace, or worse, granted one belonging to a sibling.
    """

    compose = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text(
        encoding="utf-8"
    )
    for index in range(4):
        slot = slot_for_index(index)
        expected = (
            f"{slot.root.as_posix()}:mode=0700,"
            f"uid={slot.uid},gid={slot.gid},noexec,nosuid,nodev"
        )
        assert expected in compose, expected
