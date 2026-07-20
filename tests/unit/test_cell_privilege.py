"""Tests for the per-cell uid privilege state ([2026] VJS-CC-VJS 7 J3/J5).

These drive the parser and the fail-closed rules against synthetic ``/proc``
status files, because the real transitions need capabilities the test runner does
not have. The real transitions are proved separately, in-container, under the
exact granted posture; that is J7's job and it is not faked here.

What IS held here is the part that decides whether a boundary is believed: the
code must read the kernel's answer and refuse anything short of it, and it must
never report that per-cell separation is in force when it is not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boltrig.fleet.infrastructure.cell_privilege import (
    PrivilegeError,
    assert_cell_process_unprivileged,
    assert_unprivileged,
    per_cell_uid_mode_available,
    read_privilege_state,
)

_DROPPED = """\
Name:\tpython3
Uid:\t20001\t20001\t20001\t20001
Gid:\t20001\t20001\t20001\t20001
NoNewPrivs:\t1
CapInh:\t0000000000000000
CapPrm:\t0000000000000000
CapEff:\t0000000000000000
CapBnd:\t00000000000000c0
CapAmb:\t0000000000000000
"""

_SPAWNER = """\
Name:\tpython3
Uid:\t0\t0\t0\t0
Gid:\t0\t0\t0\t0
NoNewPrivs:\t1
CapInh:\t0000000000000000
CapPrm:\t00000000000000c0
CapEff:\t00000000000000c0
CapBnd:\t00000000000000c0
CapAmb:\t0000000000000000
"""


def _status(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "status"
    path.write_text(body, encoding="ascii")
    return path


@pytest.mark.unit
def test_a_properly_dropped_process_is_accepted(tmp_path: Path) -> None:
    state = assert_unprivileged(
        expected_uid=20001, status_path=_status(tmp_path, _DROPPED)
    )
    assert state.uid == 20001
    assert state.holds_no_capabilities
    assert state.no_new_privs


@pytest.mark.unit
@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("Uid:\t0\t0\t0\t0", "root"),
        ("CapPrm:\t00000000000000c0", "capabilities"),
        ("CapEff:\t0000000000000001", "capabilities"),
        ("CapInh:\t0000000000000001", "capabilities"),
        ("CapAmb:\t0000000000000001", "capabilities"),
        ("NoNewPrivs:\t0", "no_new_privs"),
    ],
)
def test_every_way_of_being_privileged_is_refused(
    tmp_path: Path, mutation: str, reason: str
) -> None:
    """Fail closed on each limb independently, not just the obvious one.

    ``no_new_privileges`` is checked because it is one of the two legs that stop a
    dropped process regaining privilege through ``execve``; the other is the
    absence of setuid binaries, stripped from the image under J4.
    """

    field = mutation.split(":")[0]
    body = "\n".join(
        mutation if line.startswith(field + ":") else line
        for line in _DROPPED.splitlines()
    )
    with pytest.raises(PrivilegeError):
        assert_unprivileged(status_path=_status(tmp_path, body))


@pytest.mark.unit
def test_a_process_running_as_the_wrong_uid_is_refused(tmp_path: Path) -> None:
    """A cell must be ITS OWN uid, not merely some non-root uid.

    Under VJS-CC-VJS 7 the separation IS the distinct uid, so a cell that dropped
    to a sibling's uid has no boundary even though it looks unprivileged.
    """

    with pytest.raises(PrivilegeError, match="expected"):
        assert_unprivileged(expected_uid=20002, status_path=_status(tmp_path, _DROPPED))


@pytest.mark.unit
def test_per_cell_mode_is_reported_from_the_kernel_not_from_intent(
    tmp_path: Path,
) -> None:
    """The lane must never CLAIM per-cell separation it does not have.

    Reporting the mode from an env var or a config flag would let a deployment
    assert isolation while every cell shares one uid, which is precisely the state
    VJS-CC-VJS 5 found to be a cross-tenant bearer disclosure. So the answer comes
    from uid plus permitted set, which a deployment cannot set aspirationally.
    """

    assert per_cell_uid_mode_available(_status(tmp_path, _SPAWNER)) is True
    assert per_cell_uid_mode_available(_status(tmp_path, _DROPPED)) is False


@pytest.mark.unit
def test_per_cell_mode_is_false_for_an_unprivileged_root_process(
    tmp_path: Path,
) -> None:
    """uid 0 alone is not enough: without the capability there is nothing to mint."""

    body = _SPAWNER.replace("CapPrm:\t00000000000000c0", "CapPrm:\t0000000000000000")
    assert per_cell_uid_mode_available(_status(tmp_path, body)) is False


@pytest.mark.unit
def test_per_cell_mode_is_false_when_proc_cannot_be_read(tmp_path: Path) -> None:
    """An unreadable state is an unproven state, so the answer is no."""

    assert per_cell_uid_mode_available(tmp_path / "absent") is False


@pytest.mark.unit
def test_a_missing_capability_field_is_treated_as_unknown_bad(tmp_path: Path) -> None:
    """A kernel that does not report CapAmb must not read as "ambient is empty"."""

    body = "\n".join(
        line for line in _DROPPED.splitlines() if not line.startswith("CapAmb:")
    )
    with pytest.raises(PrivilegeError, match="capabilities"):
        assert_unprivileged(status_path=_status(tmp_path, body))


@pytest.mark.unit
def test_an_unparseable_status_is_an_error_not_a_default(tmp_path: Path) -> None:
    with pytest.raises(PrivilegeError):
        read_privilege_state(_status(tmp_path, "Name:\tpython3\n"))


@pytest.mark.unit
def test_a_cell_process_is_judged_from_proc_not_from_what_it_claims() -> None:
    """J5: the kernel reads the cell's /proc; the cell never self-reports.

    A compromised cell is exactly the one that would report a clean state, so
    self-attestation would be worth nothing at the moment it matters most.
    """

    import os

    # This process is a real, live, unprivileged process, so it stands in for a
    # cell. It has no_new_privs unset (a shell does not set it), which is itself
    # one of the conditions, so the assertion must REFUSE it.
    with pytest.raises(PrivilegeError):
        assert_cell_process_unprivileged(os.getpid())


@pytest.mark.unit
@pytest.mark.parametrize("pid", [0, 1, -1])
def test_a_cell_privilege_check_needs_a_real_pid(pid: int) -> None:
    with pytest.raises(PrivilegeError, match="real pid"):
        assert_cell_process_unprivileged(pid)


@pytest.mark.unit
def test_an_unreadable_cell_proc_is_refused_rather_than_assumed_clean() -> None:
    """A cell whose /proc we cannot read is a cell we cannot vouch for."""

    with pytest.raises(PrivilegeError, match="unreadable"):
        assert_cell_process_unprivileged(4_194_303)  # above any real pid
