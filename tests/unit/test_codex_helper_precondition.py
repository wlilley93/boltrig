"""The precondition that decides whether the trusted-Codex tests can prove anything.

`_assert_shared_helper` walks EVERY ancestor of the helper and refuses on the
first one this euid owns, because an owner of any containing directory can unlink
the helper and put its own program there. So the precondition guarding those test
modules has to be the CONJUNCTION: every ancestor foreign-owned.

This file exists because the first version used `any`, and `any` passed both of
its checks:

    as my own uid   ->  51 passed   (every ancestor really is root's)
    as root         ->  51 skipped  (every ancestor is ours, so any == all)

Root is the degenerate case where the two agree, so neither run could tell them
apart. On a GitHub runner where /usr belongs to the runner account but / still
belongs to root, `any` found / , declined to skip, and all 25 tests failed exactly
as before the "fix".

The discriminating case is a MIXED chain - some ancestors ours, some not - and it
needs no special privileges at all: a directory this account owns, under one it
does not. That is what the tests below construct, so the ANY-vs-ALL distinction is
now checkable by anyone running the suite normally.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from tests.unit.test_codex_trusted_proxy_provider import _every_ancestor_is_foreign


def test_a_chain_we_own_nothing_of_is_a_boundary() -> None:
    """/bin/sh resolves under /usr, root-owned on any ordinary machine."""
    if os.geteuid() == 0:
        pytest.skip("as root every ancestor is ours; the positive case cannot arise")
    assert _every_ancestor_is_foreign(os.path.realpath("/bin/sh")) is True


def test_a_MIXED_chain_is_not_a_boundary() -> None:
    """THE case that separates all from any, and the one the runner hits.

    A directory we own, inside one we do not. `any` sees the root-owned outer
    directory and says "boundary available"; `all` sees the one we own and says
    no - which is what `_assert_shared_helper` will conclude a moment later, at
    which point a non-skipped test fails instead of skipping.
    """
    if os.geteuid() == 0:
        pytest.skip("as root there is no mixed chain to build; every dir is ours")
    with tempfile.TemporaryDirectory() as outer:
        # `outer` is ours, its parent (/tmp or $TMPDIR) is not.
        helper = Path(outer) / "helper"
        helper.write_text("#!/bin/sh\n", encoding="utf-8")
        assert _every_ancestor_is_foreign(str(helper)) is False


def test_a_chain_entirely_ours_is_not_a_boundary() -> None:
    """The root case, kept because it is what the first version got right."""
    home = Path.home()
    if home.stat().st_uid != os.geteuid():
        pytest.skip("this account does not own its own home; the case cannot be built")
    nested = home / ".cache"
    if not nested.is_dir() or nested.stat().st_uid != os.geteuid():
        pytest.skip("no account-owned nested directory to test with")
    # Every ancestor up to / is NOT ours here (/ is root's), so this asserts the
    # weaker true statement: the immediate chain contains something we own.
    assert _every_ancestor_is_foreign(str(nested / "anything")) is False


def test_a_path_with_no_parents_is_refused() -> None:
    """Fail closed on a degenerate input rather than returning True vacuously."""
    assert _every_ancestor_is_foreign("/") is False


def test_the_two_modules_agree_on_the_precondition() -> None:
    """Both trusted-lane modules must gate on the SAME predicate.

    They carry their own copy (each is standalone), so this pins that a change to
    one is a change to both - otherwise one module skips on a runner and the
    other fails on it, which is the state this whole exercise started from.
    """
    from tests.unit import test_codex_kernel_tools_lane as lane
    from tests.unit import test_codex_trusted_proxy_provider as provider

    probe = os.path.realpath("/bin/sh")
    assert lane._every_ancestor_is_foreign(probe) == provider._every_ancestor_is_foreign(probe)
