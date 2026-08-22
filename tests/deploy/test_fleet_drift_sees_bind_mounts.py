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


# --------------------------------------------------------------------------- #
# The pinned TAG must name the pinned DIGEST (the second thing drift could not see)
# --------------------------------------------------------------------------- #
@pytest.mark.invariant("FR-OPS-06")
def test_the_pinned_tag_is_kept_and_verified_not_discarded() -> None:
    """`pinned()` used to throw the tag away and compare digests only.

    Docker resolves by digest, so `:0.4.14@sha256:X` and `:not-a-release@sha256:X`
    pull identical bytes and both read as correct forever. Proved by seeding: with
    the tag mispinned the DIGEST row still says `ok`, which is exactly why nothing
    caught it.
    """
    body = inspect.getsource(check_fleet_drift.pinned)
    assert "_PINNED_REF" in body, "the tag is discarded again, so nothing verifies it"
    assert hasattr(check_fleet_drift, "tag_resolution")


@pytest.mark.invariant("FR-OPS-06")
def test_only_our_own_immutable_tags_are_failed_on() -> None:
    """A floating third-party tag moving is upstream working, not a defect.

    `redis:7` and `pgvector/pgvector:pg16` move whenever upstream publishes, and a
    digest pin is precisely how a deployment survives that. Failing on them would
    redden this check on every upstream release, for a condition nobody should act
    on - the cry-wolf failure that made `gate-status` unreadable.
    """
    ours = "ghcr.io/wlilley93/boltrig-"
    decide = check_fleet_drift.tag_state_is_a_defect
    # upstream moving a floating tag: reported, never failed on
    assert decide("TAG MOVED", "docker.io/library/redis", ours) is False
    assert decide("TAG MOVED", "pgvector/pgvector", ours) is False
    # our own immutable release tags: both states are defects
    assert decide("TAG MOVED", "ghcr.io/wlilley93/boltrig-kernel", ours) is True
    assert decide("TAG MISSING", "ghcr.io/wlilley93/boltrig-ui", ours) is True
    # a resolved tag is never a defect, whoever published it
    assert decide("ok", "ghcr.io/wlilley93/boltrig-kernel", ours) is False
    # and with no remote we cannot tell them apart, so nothing is failed on
    assert decide("TAG MISSING", "ghcr.io/wlilley93/boltrig-kernel", None) is False

    prefix = inspect.getsource(check_fleet_drift.first_party_prefix)
    assert "remote" in prefix and "origin" in prefix, (
        "first-party images are identified by a hand list again; it will go stale "
        "the first time an image is added or renamed"
    )


@pytest.mark.invariant("FR-OPS-06")
def test_a_private_package_is_actually_reachable_by_the_check() -> None:
    """Anonymous auth returns 403 on the first-party kernel, fleet and Worker images.

    Assuming an anonymous token was enough would have made this whole check inert
    on exactly the three images that matter, while the one public package reported
    fine - a check that cannot fail on its real subject.
    """
    body = inspect.getsource(check_fleet_drift.tag_resolution)
    assert "_registry_auth" in body, "the check no longer presents a credential"
    auth = inspect.getsource(check_fleet_drift._registry_auth)
    assert "config.json" in auth and "auths" in auth


@pytest.mark.invariant("FR-OPS-06")
def test_docker_hub_references_are_expanded_before_being_asked_about() -> None:
    """`redis:7` names no registry and no namespace, and Hub issues tokens elsewhere.

    Without both expansions every third-party image reported NOT CHECKED, which
    fails the command - red on every run, for reasons nobody can act on.
    """
    # Asserted as VALUES, not as substrings of the source. Reading the source for
    # `"auth.docker.io" in body` is the shape of validating a URL by substring, and
    # CodeQL is right to flag it wherever it appears - a hostname test that passes on
    # any string merely CONTAINING the host is not a test of the host. Equality on a
    # named constant says the same thing and cannot be satisfied by an accident.
    assert check_fleet_drift.HUB_REGISTRY == "registry-1.docker.io"
    assert check_fleet_drift.HUB_IMPLICIT_NAMESPACE == "library", (
        "official images are not given their implicit namespace"
    )
    assert check_fleet_drift.HUB_TOKEN_HOST == "auth.docker.io", (
        "Hub's token host differs from the host that serves its manifests"
    )
    assert check_fleet_drift.HUB_TOKEN_SERVICE == "registry.docker.io"
    # and the three are genuinely distinct, which is the whole reason they are named
    assert len({
        check_fleet_drift.HUB_REGISTRY,
        check_fleet_drift.HUB_TOKEN_HOST,
        check_fleet_drift.HUB_TOKEN_SERVICE,
    }) == 3
    # the resolver must actually USE them rather than carry them as decoration
    body = inspect.getsource(check_fleet_drift.tag_resolution)
    for const in ("HUB_REGISTRY", "HUB_TOKEN_HOST", "HUB_TOKEN_SERVICE",
                  "HUB_IMPLICIT_NAMESPACE"):
        assert const in body, f"{const} is defined but tag_resolution does not use it"


@pytest.mark.invariant("FR-OPS-06")
def test_a_mismatched_tag_fails_the_command() -> None:
    """A report nobody exits non-zero on is a log line, not a check."""
    main = inspect.getsource(check_fleet_drift.main)
    assert "PINNED TAG DOES NOT MATCH THE REGISTRY" in main
    block = main[main.index("if bad_tags:"):]
    assert "return 1" in block
    # and it points at the fix that removes the class rather than detecting it
    assert "boltrig-images.env" in main, (
        "the remedy no longer names generating the pin from the release record, "
        "which is what makes a wrong tag impossible rather than merely visible"
    )
