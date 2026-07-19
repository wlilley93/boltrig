"""The named per-cell isolation boundary ([2026] VJS-CC-VJS 5).

The court found that attestation proves the PROVENANCE of a connection and not
the INTEGRITY of the program that makes it, so the helper the App Server executes
must be beyond the reach of every cell. Under one shared uid a file MODE proves
nothing, so these cases pin the only questions that matter: is it owned by
somebody else, and can this account write it or any directory above it.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest

from boltrig.fleet.infrastructure.codex_cell_boundary import (
    BOUNDARY_MECHANISM,
    DEFAULT_SHARED_HELPER_PATH,
    SHARED_HELPER_ENV_KEY,
    CodexCellBoundaryError,
    assert_cell_isolation_boundary,
    assert_ptrace_scope,
    resolve_shared_helper_path,
)

_STACK_ROOT = Path("/var/lib/boltrig/codex-cells")


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_an_absent_override_resolves_the_image_default(raw: str | None) -> None:
    env: dict[str, str] = {} if raw is None else {SHARED_HELPER_ENV_KEY: raw}
    assert resolve_shared_helper_path(env) == DEFAULT_SHARED_HELPER_PATH


@pytest.mark.parametrize("raw", ["relative/helper", "/opt/../opt/helper", "/opt/./helper"])
def test_an_unnormalized_or_relative_override_is_refused(raw: str) -> None:
    with pytest.raises(CodexCellBoundaryError):
        resolve_shared_helper_path({SHARED_HELPER_ENV_KEY: raw})


def test_a_helper_this_account_owns_is_no_boundary(tmp_path: Path) -> None:
    """An owner can always chmod write back, so ownership is the real question."""

    helper = tmp_path / "helper"
    helper.write_text("#!/bin/sh\nexit 0\n")
    helper.chmod(0o555)
    with pytest.raises(CodexCellBoundaryError, match="owned by this account"):
        assert_cell_isolation_boundary(
            stack_root=_STACK_ROOT,
            env={SHARED_HELPER_ENV_KEY: os.fspath(helper)},
            require_ptrace_scope=False,
        )


def test_a_missing_helper_is_refused(tmp_path: Path) -> None:
    with pytest.raises(CodexCellBoundaryError, match="not accessible"):
        assert_cell_isolation_boundary(
            stack_root=_STACK_ROOT,
            env={SHARED_HELPER_ENV_KEY: os.fspath(tmp_path / "absent")},
            require_ptrace_scope=False,
        )


def test_a_symlinked_helper_is_refused(tmp_path: Path) -> None:
    """A symlink we can replace would let us redirect the executed program."""

    target = tmp_path / "real"
    target.write_text("#!/bin/sh\nexit 0\n")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(CodexCellBoundaryError, match="symlink"):
        assert_cell_isolation_boundary(
            stack_root=_STACK_ROOT,
            env={SHARED_HELPER_ENV_KEY: os.fspath(link)},
            require_ptrace_scope=False,
        )


def test_a_directory_is_not_a_helper(tmp_path: Path) -> None:
    with pytest.raises(CodexCellBoundaryError, match="regular file"):
        assert_cell_isolation_boundary(
            stack_root=_STACK_ROOT,
            env={SHARED_HELPER_ENV_KEY: os.fspath(tmp_path)},
            require_ptrace_scope=False,
        )


def test_a_helper_inside_the_mutable_stack_root_is_refused(tmp_path: Path) -> None:
    """The stack root is the tmpfs every cell can write, so nothing there qualifies."""

    helper = tmp_path / "helper"
    helper.write_text("#!/bin/sh\nexit 0\n")
    with pytest.raises(CodexCellBoundaryError, match="outside the mutable stack root"):
        assert_cell_isolation_boundary(
            stack_root=tmp_path,
            env={SHARED_HELPER_ENV_KEY: os.fspath(helper)},
            require_ptrace_scope=False,
        )


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write everything, so nothing is proved")
def test_a_root_owned_helper_on_an_unwritable_chain_is_a_boundary() -> None:
    """The real shape: another account owns it and we cannot write the chain.

    ``/bin/sh`` stands in for the baked image helper: root-owned, executable, on a
    directory chain this account cannot write. That is exactly the property the
    image bakes at /opt/boltrig/codex/model_auth_helper.
    """

    shell = Path("/bin/sh").resolve()
    boundary = assert_cell_isolation_boundary(
        stack_root=_STACK_ROOT,
        env={SHARED_HELPER_ENV_KEY: os.fspath(shell)},
        require_ptrace_scope=False,
    )
    assert boundary.mechanism == BOUNDARY_MECHANISM
    assert boundary.helper_path == shell
    assert boundary.helper_sha256 == "sha256:" + hashlib.sha256(shell.read_bytes()).hexdigest()
    # Load-bearing admission, not a formality: flipping it must be deliberate.
    assert boundary.config_toml_protected is False


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write everything, so nothing is proved")
def test_a_writable_ancestor_defeats_an_unwritable_helper(tmp_path: Path) -> None:
    """A cell that can write the directory can unlink the helper and drop its own."""

    nested = tmp_path / "nested"
    nested.mkdir()
    helper = nested / "helper"
    helper.write_text("#!/bin/sh\nexit 0\n")
    helper.chmod(0o555)
    with pytest.raises(CodexCellBoundaryError):
        assert_cell_isolation_boundary(
            stack_root=_STACK_ROOT,
            env={SHARED_HELPER_ENV_KEY: os.fspath(helper)},
            require_ptrace_scope=False,
        )


def test_ptrace_scope_accepts_restricted_and_above(tmp_path: Path) -> None:
    for value in ("1", "2", "3"):
        sysctl = tmp_path / f"scope-{value}"
        sysctl.write_text(f"{value}\n")
        assert assert_ptrace_scope(sysctl) == int(value)


def test_ptrace_scope_refuses_classic_yama_and_unreadable_or_malformed(tmp_path: Path) -> None:
    """Scope 0 lets a sibling cell read another's memory, so it is fatal not advisory."""

    classic = tmp_path / "zero"
    classic.write_text("0\n")
    with pytest.raises(CodexCellBoundaryError, match="below the required"):
        assert_ptrace_scope(classic)
    malformed = tmp_path / "junk"
    malformed.write_text("not-a-number\n")
    with pytest.raises(CodexCellBoundaryError, match="malformed"):
        assert_ptrace_scope(malformed)
    with pytest.raises(CodexCellBoundaryError, match="unreadable"):
        assert_ptrace_scope(tmp_path / "absent")


@pytest.mark.skipif(sys.platform != "linux", reason="yama is a Linux sysctl")
def test_the_host_ptrace_scope_is_a_recorded_deployment_precondition() -> None:
    """This sysctl is NOT namespaced: we can prove it, we cannot set it.

    Read-only assertion of a host property, so a box that drops to 0 fails loudly
    rather than silently losing sibling-cell memory isolation.
    """

    assert assert_ptrace_scope() >= 1
