"""`fleet-drift` must see bind-mounted trees, not only image digests (FR-OPS-06).

WHY THIS EXISTS. On 2026-07-27 `app.boltrig.io` served a digest-pinned kernel image
while bind-mounting `libraries/` from a checkout of main that was FIFTY-SEVEN
commits behind. A merged fix to the opbox skill - its eight `tool_grants` named the
kernel door's noun-first verbs while the tenant runs the frontend door's verb-first
ones, so ZERO of them resolved and the skill's opbox reach was nil - sat undelivered
for three days. It landed only because an unrelated retirement happened to `git
pull` that tree.

Every image was correctly pinned the whole time. That is the point: a bind-mounted
directory is a deployment surface exactly like an image tag, and digest pinning does
nothing for it.

WHAT IS CHECKED HERE, offline. The drift script cannot be run in CI - it needs a
box, and the claim "tenant X runs digest Y" is only answerable by asking tenant X.
So these assert the SHAPE of the check rather than its verdict: that it looks at
bind mounts at all, that staleness is scoped to the mounted path rather than the
whole repository, and that a detached HEAD is reported instead of measured. Each is
a property that, if lost, would return the tool to being blind in the exact way that
cost three days.

Scoping is the one that decides whether the tool survives contact with use. Counting
`HEAD..origin/main` over the whole checkout goes red the moment anything merges,
which makes the check permanently red and therefore ignored - the cry-wolf failure
`gate-status` had on the same day. Ten commits behind, none touching `libraries/`,
is not a stale deploy.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from scripts import check_fleet_drift

_SOURCE = Path(check_fleet_drift.__file__).read_text(encoding="utf-8")


@pytest.mark.invariant("FR-OPS-06")
def test_the_drift_check_reads_bind_mounts_at_all() -> None:
    assert hasattr(check_fleet_drift, "bind_mounted_repos"), (
        "fleet-drift no longer inspects bind mounts, so a container serving stale "
        "files from the host filesystem is invisible to it again"
    )
    body = inspect.getsource(check_fleet_drift.bind_mounted_repos)
    assert 'eq .Type "bind"' in body, "the mount query no longer filters to bind mounts"
    assert "docker inspect" in body


@pytest.mark.invariant("FR-OPS-06")
def test_staleness_is_scoped_to_the_mounted_path_not_the_whole_repository() -> None:
    """The difference between a usable check and one that is always red.

    `rev-list HEAD..origin/<branch>` with no pathspec counts every unmerged commit
    in the repository. With ` -- <path>` it counts only those that touch the bytes
    this container actually reads.
    """
    body = inspect.getsource(check_fleet_drift.bind_mounted_repos)
    assert "rev-list --count" in body
    assert '-- \\"$rel\\"' in body or '-- "$rel"' in body, (
        "the commit count has no pathspec, so it measures the repository rather "
        "than the mounted path and will be red on every unrelated merge"
    )
    # and the relative path is derived from the mount, not assumed
    assert 'rel=${src#' in body


@pytest.mark.invariant("FR-OPS-06")
def test_a_detached_head_is_reported_rather_than_measured() -> None:
    """`rev-parse --abbrev-ref HEAD` returns the literal "HEAD" when detached.

    Comparing that against `origin/HEAD` yields a number about the wrong ref, which
    is worse than no number. A deployment tree not on a branch is itself the
    finding.
    """
    body = inspect.getsource(check_fleet_drift.bind_mounted_repos)
    assert "DETACHED" in body
    assert "= HEAD ]" in body, "a detached HEAD is still being compared against origin/HEAD"


@pytest.mark.invariant("FR-OPS-06")
def test_a_stale_mount_fails_the_command_rather_than_only_printing() -> None:
    """A report nobody exits non-zero on is a log line, not a check."""
    main = inspect.getsource(check_fleet_drift.main)
    assert "STALE BIND MOUNT" in main
    stale_block = main[main.index("if stale:"):]
    assert "return 1" in stale_block, "a stale bind mount does not fail the command"


@pytest.mark.invariant("FR-OPS-06")
def test_the_pass_message_does_not_claim_more_than_was_checked() -> None:
    """The result line must name BOTH halves, or a green reads as covering only one."""
    main = inspect.getsource(check_fleet_drift.main)
    assert "RESULT: PASS" in main
    pass_line = main[main.index("RESULT: PASS"):]
    assert "bind-mounted" in pass_line, (
        "the pass message mentions only images, so a green would read as proving "
        "something the check now measures twice as much of"
    )
