"""A stalled loop must be distinguishable from an idle one, in the log.

The 2026-07-30 session-distillation wedge wrote 20 of 89 conversations and then
stopped forever: healthy container, zero errors, no log output at all for seven
minutes. Nothing raised, because nothing in that failure was going to raise.
"""

from __future__ import annotations

import logging

from boltrig.fleet.sweep_progress import STALL_CYCLES, SweepProgress


def test_idle_and_working_are_named_differently():
    p = SweepProgress("t")
    assert p.record(seen=0, acted=0) == "idle"
    assert p.record(seen=69, acted=20) == "working"
    assert p.total_acted == 20


def test_seeing_work_and_doing_none_escalates_to_stalled():
    """The state that hid for seven minutes.

    One such cycle is not a verdict - a lock, a transient refusal or a race all
    look like it. STALL_CYCLES consecutive ones are a pattern.
    """
    p = SweepProgress("t")
    for _ in range(STALL_CYCLES - 1):
        assert p.record(seen=20, acted=0) == "idle-ish"
    assert p.record(seen=20, acted=0) == "stalled"


def test_a_single_success_clears_the_stall():
    p = SweepProgress("t")
    for _ in range(STALL_CYCLES):
        p.record(seen=20, acted=0)
    assert p.record(seen=20, acted=5) == "working"
    assert p.consecutive_stalled == 0


def test_a_stall_is_logged_at_WARNING_not_info(caplog):
    """A stalled sweep that whispers at INFO is the silence problem again."""
    p = SweepProgress("t")
    with caplog.at_level(logging.INFO, logger="boltrig.fleet.sweep_progress"):
        for _ in range(STALL_CYCLES):
            p.record(seen=20, acted=0)
    levels = [r.levelno for r in caplog.records]
    assert logging.WARNING in levels, "a stall must not whisper at INFO"
    assert any("STALLED" in r.getMessage() for r in caplog.records)


def test_pending_makes_a_wrong_SELECTION_visible():
    """The case seen/acted alone CANNOT catch, and why `pending` exists.

    The real wedge filtered every candidate away, so the loop honestly saw
    nothing. seen=0/acted=0 is idle by definition. Only an INDEPENDENT count of
    waiting work distinguishes "nothing to do" from "my query is broken".
    """
    p = SweepProgress("t")
    assert p.record(seen=0, acted=0, pending=0) == "idle"

    q = SweepProgress("t")
    for _ in range(STALL_CYCLES - 1):
        assert q.record(seen=0, acted=0, pending=69) == "idle-ish"
    assert q.record(seen=0, acted=0, pending=69) == "stalled", (
        "work waiting while the loop sees none is the wedge signature"
    )


def test_seen_acted_alone_would_have_MISSED_the_real_wedge():
    """Pins the documented blind spot, so nobody mistakes this for total cover.

    Without an independent `pending`, the actual 2026-07-30 failure reports idle.
    That is a true statement about the counters and a false one about the system,
    which is exactly why the module docstring says so out loud.
    """
    p = SweepProgress("t")
    verdicts = {p.record(seen=0, acted=0) for _ in range(STALL_CYCLES + 2)}
    assert verdicts == {"idle"}, (
        "documented limitation: with no independent pending count, a broken "
        "SELECTION is indistinguishable from an idle loop"
    )
