"""Prove the read-only filesystem sandbox ENGAGES on this host, or refuse to start.

WHAT WAS BEING TAKEN ON TRUST. ``codex_runtime_config_toml`` writes
``sandbox_mode = "read-only"`` into the generated config, and
``test_codex_managed_config`` reads that same line back out. Every assertion this
estate makes about the cell wall is therefore an assertion about OUR OWN BYTES.
The mechanism that actually refuses a write belongs to the kernel: the pinned
Codex binary carries 38 Landlock and 21 seccomp symbols (measured on the shipped
artefact, not recalled), and Landlock is an LSM a host may simply not have. On a
kernel built without it, or one where it is absent from
``/sys/kernel/security/lsm``, the config line stays true, the enforcement is gone,
and nothing on this estate goes red.

The gap was RECORDED rather than hidden: ``QUARANTINED_PREFLIGHT_BLOCKERS`` already
names ``effective_config`` a production blocker and
``QuarantinedCodexPreflightReceipt.production_complete`` is hard-coded False. What
was missing was the instrument. This module is the instrument, in the idiom
``codex_cell_boundary`` established: derive the answer from the kernel, never from
configuration, and fail closed when it cannot be derived.

WHY THREE LEGS AND NOT ONE. "The sandboxed write was refused" proves nothing on its
own, and it fails in two opposite directions:

  * If the probe path were unwritable anyway, the refusal is the filesystem's and
    not the sandbox's, and this check could never fail. So leg one writes that exact
    path with NO sandbox and requires it to SUCCEED.
  * If Codex never launched, every command "fails" and the refusal reads exactly
    like enforcement. So leg three runs a READ under the same sandbox and requires
    it to SUCCEED.

Leg two is the claim, and it asserts on the ARTEFACT: the file must not exist
afterwards. The exit code belongs to the shell inside the sandbox rather than to
Codex (a refused redirect exits 2), so a check keyed on the number would be reading
the helper instead of the thing it stands for.

HERMETIC BY CONSTRUCTION. The probe runs with an empty ``CODEX_HOME`` and ``HOME``.
Without that it would inherit the operator's ``config.toml``, and a probe that can
be turned green by a file in a developer's home directory measures that file rather
than the host.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PROBE_TIMEOUT_SECONDS = 60.0
MAX_PROBE_TIMEOUT_SECONDS = 300.0
SANDBOX_MECHANISM = "codex-linux-sandbox-landlock-seccomp"
_READ_PROBE_SOURCE = Path("/etc/hostname")
_READ_PROBE_BYTES = 1
_PROBE_ENV_PATH = "/usr/bin:/bin"


class CodexSandboxEngagementError(RuntimeError):
    """The read-only sandbox is not proved to engage, so no cell may start."""


@dataclass(frozen=True, slots=True)
class SandboxEngagementProof:
    """One proved statement that the sandbox refuses writes on THIS host.

    Every field is an observation, not a setting. ``refusal_detail`` carries the
    kernel's own words back to the operator, because a refusal that does not say
    what refused it cannot be acted on.
    """

    mechanism: str
    codex_path: Path
    probe_path: Path
    unsandboxed_write_succeeded: bool
    sandboxed_write_refused: bool
    sandboxed_read_succeeded: bool
    refusal_detail: str


def _validated_timeout(timeout_seconds: float) -> float:
    if type(timeout_seconds) not in {int, float}:
        raise TypeError("probe timeout must be a number")
    timeout = float(timeout_seconds)
    if not 0 < timeout <= MAX_PROBE_TIMEOUT_SECONDS:
        raise ValueError("probe timeout is outside its bounded range")
    return timeout


def _validated_binary(codex_binary: Path) -> Path:
    if not isinstance(codex_binary, Path) or not codex_binary.is_absolute():
        raise CodexSandboxEngagementError("codex binary must be an absolute Path")
    if not codex_binary.is_file() or not os.access(codex_binary, os.X_OK):
        raise CodexSandboxEngagementError(
            f"codex binary {codex_binary} is not an executable file, so the sandbox "
            "is UNPROVED on this host. That is refused, not skipped."
        )
    return codex_binary


def _run_sandboxed(
    codex_binary: Path,
    codex_home: Path,
    home: Path,
    script: str,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    """Run one shell command under Codex's own read-only sandbox, hermetically."""

    env = {
        "CODEX_HOME": str(codex_home),
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": _PROBE_ENV_PATH,
    }
    try:
        return subprocess.run(
            [
                str(codex_binary),
                "sandbox",
                "-c",
                'sandbox_mode="read-only"',
                "--",
                "/bin/sh",
                "-c",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=str(home),
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise CodexSandboxEngagementError(
            "the sandbox probe timed out, so engagement is UNPROVED"
        ) from None
    except OSError as error:
        raise CodexSandboxEngagementError(
            f"the sandbox probe could not be launched ({error.strerror}), so "
            "engagement is UNPROVED"
        ) from None


def _assert_unsandboxed_write_works(probe_path: Path) -> None:
    """Leg one. Without this the whole check could never fail (vacuity guard).

    If the probe path were unwritable for any unrelated reason, leg two's "the file
    is absent" would be true on a host with NO sandbox at all.
    """

    try:
        probe_path.write_text("probe", encoding="ascii")
    except OSError as error:
        raise CodexSandboxEngagementError(
            f"the probe path {probe_path} is not writable WITHOUT the sandbox "
            f"({error.strerror}), so a refusal under it would prove nothing about "
            "the sandbox. Choose a writable probe root."
        ) from None
    probe_path.unlink()


def _assert_sandboxed_write_refused(
    codex_binary: Path, codex_home: Path, home: Path, probe_path: Path, timeout: float
) -> str:
    """Leg two, the claim. Asserted on the artefact, never on an exit code."""

    result = _run_sandboxed(
        codex_binary, codex_home, home, f"printf probe > {probe_path}", timeout
    )
    if probe_path.exists():
        probe_path.unlink(missing_ok=True)
        raise CodexSandboxEngagementError(
            f"THE SANDBOX DID NOT ENGAGE: a write to {probe_path} SUCCEEDED under "
            'sandbox_mode="read-only". The generated config is honest and the '
            "enforcement is absent, which is the exact state every cell-wall claim "
            "on this estate assumes away. Check that this kernel carries landlock "
            "in /sys/kernel/security/lsm."
        )
    detail = (result.stderr or result.stdout).strip().splitlines()
    return detail[-1] if detail else "(the sandbox refused without a message)"


def _assert_sandboxed_read_works(
    codex_binary: Path, codex_home: Path, home: Path, timeout: float
) -> None:
    """Leg three, the negative control.

    A Codex that fails to launch refuses everything, and that reads exactly like
    enforcement. A sandbox that permits nothing would also break the product, so
    this leg is what makes leg two a statement about WRITES.
    """

    result = _run_sandboxed(
        codex_binary,
        codex_home,
        home,
        f"head -c {_READ_PROBE_BYTES} {_READ_PROBE_SOURCE}",
        timeout,
    )
    if result.returncode != 0 or len(result.stdout) < _READ_PROBE_BYTES:
        raise CodexSandboxEngagementError(
            f"the sandboxed READ of {_READ_PROBE_SOURCE} failed (rc="
            f"{result.returncode}, stderr={result.stderr.strip()!r}). The write "
            "refusal above therefore proves nothing: a runtime that cannot run "
            "anything refuses writes for the wrong reason."
        )


def prove_sandbox_engagement(
    *,
    codex_binary: Path,
    probe_root: Path,
    timeout_seconds: float = DEFAULT_PROBE_TIMEOUT_SECONDS,
) -> SandboxEngagementProof:
    """Prove the read-only sandbox refuses writes on this host, right now.

    Returns the proof or raises. There is no third outcome: a probe that could not
    be run leaves engagement UNPROVED, and unproved is refused rather than skipped,
    because a sandbox reported as untested reads to every downstream caller exactly
    like one reported as working.
    """

    timeout = _validated_timeout(timeout_seconds)
    binary = _validated_binary(codex_binary)
    if not isinstance(probe_root, Path) or not probe_root.is_absolute():
        raise CodexSandboxEngagementError("probe_root must be an absolute Path")
    if not probe_root.is_dir():
        raise CodexSandboxEngagementError(f"probe_root {probe_root} is not a directory")

    try:
        scratch_manager = tempfile.TemporaryDirectory(
            prefix="boltrig-sandbox-probe-", dir=str(probe_root)
        )
    except OSError as error:
        # Found by seeding a 0500 probe root: this escaped as a raw PermissionError
        # from tempfile, which is a traceback rather than a finding. The condition is
        # the same vacuity guard leg one exists for, so it gets the same words.
        raise CodexSandboxEngagementError(
            f"no scratch directory could be made under probe_root {probe_root} "
            f"({error.strerror}), so a refusal under the sandbox would prove nothing "
            "about the sandbox. Choose a writable probe root."
        ) from None

    with scratch_manager as scratch:
        home = Path(scratch)
        codex_home = home / ".codex"
        codex_home.mkdir()
        probe_path = home / "engagement-probe"

        _assert_unsandboxed_write_works(probe_path)
        detail = _assert_sandboxed_write_refused(
            binary, codex_home, home, probe_path, timeout
        )
        _assert_sandboxed_read_works(binary, codex_home, home, timeout)

    return SandboxEngagementProof(
        mechanism=SANDBOX_MECHANISM,
        codex_path=binary,
        probe_path=probe_path,
        unsandboxed_write_succeeded=True,
        sandboxed_write_refused=True,
        sandboxed_read_succeeded=True,
        refusal_detail=detail,
    )
