"""Adversarial cross-cell tests for the per-cell boundary ([2026] VJS-CC-VJS 5 G6).

The court held that the boundary may NOT be discharged by argument, by review, or
by the absence of a known attack, but only by the adversarial test itself. So this
file plays the hostile cell: it holds full write access to everything its own uid
can reach, and tries to reach a sibling's attestation inputs.

The named vector from the judgment is the helper rewrite: cell A rewrites cell B's
auth helper, and B's App Server executes it as its own direct child, passing
ancestry attestation on the merits. G2 moved that helper onto a root-owned path on
the read-only image mount, so the rewrite must now fail at the kernel.

What is NOT closed is recorded here too, as an executable finding rather than a
paragraph: config.toml carries auth.command and must live in a CODEX_HOME the cell
uid owns, and this container holds neither CAP_SETUID nor CAP_SYS_ADMIN, so a
sibling can still replace it. That is why the provider refuses concurrent cells.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from boltrig.fleet.infrastructure.codex_cell_boundary import (
    SHARED_HELPER_ENV_KEY,
    CodexCellBoundaryError,
    assert_cell_isolation_boundary,
)

pytestmark = pytest.mark.skipif(
    os.geteuid() == 0,
    reason="root can write anything, so a boundary test proves nothing as root",
)


def _boundary(stack_root: Path):
    """The real shape: a root-owned program on a chain this account cannot write."""

    return assert_cell_isolation_boundary(
        stack_root=stack_root,
        env={SHARED_HELPER_ENV_KEY: os.path.realpath("/bin/sh")},
        require_ptrace_scope=False,
    )


def test_a_hostile_cell_cannot_rewrite_the_shared_helper(tmp_path: Path) -> None:
    """THE named vector from [2026] VJS-CC-VJS 5: rewrite a sibling's auth helper.

    Every write route is tried, not just open(): a cell that can unlink or rename
    over the path substitutes the program just as effectively as one that can write
    its bytes.
    """

    boundary = _boundary(tmp_path)
    helper = boundary.helper_path
    forged = tmp_path / "forged"
    forged.write_text("#!/bin/sh\nexfiltrate\n")

    with pytest.raises(OSError):
        with open(helper, "wb") as handle:  # noqa: PTH123 - the point is the raw call
            handle.write(b"pwned")
    with pytest.raises(OSError):
        os.chmod(helper, 0o777)
    with pytest.raises(OSError):
        os.unlink(helper)
    with pytest.raises(OSError):
        os.rename(forged, helper)
    with pytest.raises(OSError):
        os.replace(forged, helper)

    # The program the App Server will execute is byte-identical afterwards.
    assert boundary.helper_sha256 == "sha256:" + hashlib.sha256(helper.read_bytes()).hexdigest()


def test_a_hostile_cell_cannot_replace_the_directory_holding_the_helper(
    tmp_path: Path,
) -> None:
    """A writable parent is as good as a writable file, so the chain is checked."""

    boundary = _boundary(tmp_path)
    parent = boundary.helper_path.parent
    with pytest.raises(OSError):
        (parent / "planted").write_text("#!/bin/sh\nexit 0\n")
    with pytest.raises(OSError):
        os.chmod(parent, 0o777)


def test_a_hostile_cell_writes_freely_inside_its_own_root(tmp_path: Path) -> None:
    """The threat model REQUIRES this to succeed; the boundary must survive it."""

    boundary = _boundary(tmp_path)
    own_root = tmp_path / "cells" / "cell-a"
    own_root.mkdir(parents=True)
    (own_root / "anything").write_text("cell A owns this")
    (own_root / "anything").chmod(0o777)
    os.unlink(own_root / "anything")

    reproved = _boundary(tmp_path)
    assert reproved.helper_sha256 == boundary.helper_sha256


def test_the_boundary_refuses_a_helper_a_cell_could_reach(tmp_path: Path) -> None:
    """A helper back inside the mutable tree must fail closed, not warn."""

    planted = tmp_path / "model_auth_helper"
    planted.write_text("#!/bin/sh\nexit 0\n")
    planted.chmod(0o500)
    with pytest.raises(CodexCellBoundaryError):
        assert_cell_isolation_boundary(
            stack_root=tmp_path,
            env={SHARED_HELPER_ENV_KEY: os.fspath(planted)},
            require_ptrace_scope=False,
        )


def test_config_toml_is_recorded_as_an_open_vector_not_a_closed_one(tmp_path: Path) -> None:
    """G3 is OPEN and must stay visible until a boundary actually covers it.

    config.toml names the program via auth.command and sits in a CODEX_HOME the
    cell uid owns, so a sibling can replace it. Asserting the honest value here
    means closing G3 has to change this test deliberately rather than quietly.
    """

    assert _boundary(tmp_path).config_toml_protected is False
