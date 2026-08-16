"""The sandbox engagement proof must be able to FAIL, in each of its three legs.

The defect this instrument exists for is not a bug in a code path, it is a claim
resting on our own bytes: ``sandbox_mode = "read-only"`` is written by
``codex_runtime_config_toml`` and read back by ``test_codex_managed_config``, and on
a kernel without Landlock that line stays true while nothing stops a write.

So the tests that matter here are the ones that SEED an unengaged sandbox and watch
the proof go red. Asserting only against the real, working binary would produce a
green suite on a host where the sandbox was switched off entirely, which is the
whole failure.

Each leg is seeded separately, because they refuse different things:

  * a "codex" that ignores its sandbox arguments and just runs the command, which
    is exactly how a host without Landlock behaves
  * a "codex" that cannot run anything, which refuses writes for the WRONG reason
    and would otherwise read as enforcement
  * a probe path that was never writable in the first place, where a refusal is the
    filesystem's and the check could never fail
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from boltrig.fleet.infrastructure.codex_sandbox_engagement import (

    CodexSandboxEngagementError,
    SANDBOX_MECHANISM,
    prove_sandbox_engagement,
)

# Every leg here needs a Linux kernel facility macOS does not have: yama
# ptrace_scope, abstract AF_UNIX names, SO_PEERCRED, or bubblewrap. Marked so a
# non-Linux box reports them as unverified instead of failing; on Linux the
# marker is inert and they always run.
pytestmark = pytest.mark.linux_only

# A stand-in that accepts `sandbox -c <cfg> -- <cmd...>` and runs the command with NO
# sandbox at all. This is the host-without-Landlock shape, and it is the seed the
# real defect would produce.
_UNENGAGED_CODEX = """#!/bin/sh
while [ "$1" != "--" ]; do shift || exit 64; done
shift
exec "$@"
"""

# A stand-in that launches nothing. Every command "fails", which is what makes the
# read leg necessary: without it this passes the write assertion.
_DEAD_CODEX = """#!/bin/sh
echo "codex: unable to start" >&2
exit 70
"""


def _fake_codex(tmp_path: Path, name: str, script: str) -> Path:
    path = tmp_path / name
    path.write_text(script, encoding="ascii")
    path.chmod(0o755)
    return path


@pytest.fixture
def probe_root(tmp_path: Path) -> Path:
    root = tmp_path / "probes"
    root.mkdir()
    return root


def test_an_unengaged_sandbox_is_refused_and_names_the_lsm(
    tmp_path: Path, probe_root: Path
) -> None:
    """THE SEED THAT MATTERS. The config is honest; the enforcement is absent."""

    codex = _fake_codex(tmp_path, "codex-unengaged", _UNENGAGED_CODEX)

    with pytest.raises(CodexSandboxEngagementError) as caught:
        prove_sandbox_engagement(codex_binary=codex, probe_root=probe_root)

    message = str(caught.value)
    assert "THE SANDBOX DID NOT ENGAGE" in message
    # The refusal has to be actionable. "It did not engage" without naming where to
    # look sends the reader to the config, which is the one place that looks correct.
    assert "landlock" in message
    assert "/sys/kernel/security/lsm" in message


def test_a_runtime_that_cannot_run_anything_does_not_read_as_enforcement(
    tmp_path: Path, probe_root: Path
) -> None:
    """The negative control, and the reason the write leg alone proves nothing."""

    codex = _fake_codex(tmp_path, "codex-dead", _DEAD_CODEX)

    with pytest.raises(CodexSandboxEngagementError) as caught:
        prove_sandbox_engagement(codex_binary=codex, probe_root=probe_root)

    message = str(caught.value)
    assert "proves nothing" in message
    # It must NOT claim the sandbox engaged. A dead runtime refused the write too.
    assert "THE SANDBOX DID NOT ENGAGE" not in message


def test_an_unwritable_probe_root_is_refused_rather_than_silently_passing(
    tmp_path: Path
) -> None:
    """The vacuity guard: a refusal at an unwritable path is not the sandbox's."""

    if os.geteuid() == 0:
        pytest.skip("root ignores the mode bits this seed depends on")
    root = tmp_path / "read-only-root"
    root.mkdir()
    root.chmod(0o500)
    try:
        with pytest.raises(CodexSandboxEngagementError) as caught:
            prove_sandbox_engagement(
                codex_binary=_fake_codex(tmp_path, "codex-x", _UNENGAGED_CODEX),
                probe_root=root,
            )
    finally:
        root.chmod(0o700)
    assert "would prove nothing" in str(caught.value) or "probe_root" in str(caught.value)


def test_a_missing_binary_is_unproved_and_unproved_is_refused(probe_root: Path) -> None:
    """Never a skip. A sandbox reported untested reads like one reported working."""

    with pytest.raises(CodexSandboxEngagementError) as caught:
        prove_sandbox_engagement(
            codex_binary=Path("/nonexistent/codex"), probe_root=probe_root
        )
    assert "UNPROVED" in str(caught.value)
    assert "refused, not skipped" in str(caught.value)


def test_a_relative_binary_or_probe_root_is_rejected(probe_root: Path, tmp_path: Path) -> None:
    with pytest.raises(CodexSandboxEngagementError):
        prove_sandbox_engagement(codex_binary=Path("codex"), probe_root=probe_root)
    with pytest.raises(CodexSandboxEngagementError):
        prove_sandbox_engagement(
            codex_binary=_fake_codex(tmp_path, "codex-y", _UNENGAGED_CODEX),
            probe_root=Path("relative"),
        )


def test_the_timeout_is_bounded() -> None:
    with pytest.raises(ValueError):
        prove_sandbox_engagement(
            codex_binary=Path("/bin/sh"), probe_root=Path("/tmp"), timeout_seconds=0
        )
    with pytest.raises(ValueError):
        prove_sandbox_engagement(
            codex_binary=Path("/bin/sh"), probe_root=Path("/tmp"), timeout_seconds=10**6
        )


@pytest.mark.skipif(
    shutil.which("codex") is None, reason="the real Codex CLI is not on this host"
)
def test_the_real_installed_codex_actually_engages_its_sandbox(probe_root: Path) -> None:
    """The live half. Without it every assertion above is about a shell script.

    Skipped rather than failed where Codex is absent, because a check that cannot
    pass on a developer box is a check people learn to bypass. The seeded cases
    above carry the discrimination; this one carries the truth of the claim.
    """

    binary = Path(shutil.which("codex") or "")
    proof = prove_sandbox_engagement(codex_binary=binary, probe_root=probe_root)

    assert proof.mechanism == SANDBOX_MECHANISM
    assert proof.unsandboxed_write_succeeded
    assert proof.sandboxed_write_refused
    assert proof.sandboxed_read_succeeded
    # The kernel's own words, carried back so an operator can act on a failure.
    assert proof.refusal_detail
