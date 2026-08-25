"""A container removal that omits -v keeps the anonymous volume, per run, forever.

`docker run --rm` collects a container's anonymous volumes when it exits. A
cleanup trap that removes the container FIRST pre-empts that, and a removal
without the volumes flag keeps the volume. The container is then gone, so nothing
references the volume and nothing will ever collect it.

Measured on the beelink, 2026-08-24, with the pinned pgvector image the quality
gate uses: without the flag, dangling volumes went 4 to 5 (one leaked); with it,
5 to 5 (none leaked).

`scripts/with_test_postgres.sh` had the first form, so every green quality-gate
run left a ~180MB PostgreSQL data directory behind. Eleven days of runs had
accumulated 138 of them (16.7GB), most of what took that box to 88% disk, and the
same class of pressure that took the production host to 100% and aborted the
v0.4.47 roll mid-flight.

The flag is safe to require everywhere: it removes only ANONYMOUS volumes
attached to the named container, never named ones. So there is no case where
omitting it is correct, which is what makes a blanket sweep sound rather than
over-strict.

WHAT THIS SWEEP COVERS, STATED AS A BOUND RATHER THAN IMPLIED. It reads shell
scripts, Makefiles and CI workflows, where the removal appears as a literal
command. It does NOT read Python: there the arguments are a list passed to
subprocess, which a text scan cannot judge, and every occurrence of the literal
text in a .py file in this repo today is either this docstring or this file's own
matching machinery. An earlier version of this test scanned Python too and
flagged ITSELF, which is the honest reason the bound is here rather than a
convenience.

That earlier version also passed three local runs before failing in CI, because
the sweep enumerates `git ls-files` and the file was still unstaged: as far as its
own sweep was concerned it did not exist. Stage the thing a gate inspects before
believing the gate.
"""

from __future__ import annotations

from pathlib import Path
import re
import subprocess


_REPO = Path(__file__).resolve().parents[2]

# The removal verb plus its flags, up to the first argument that is not a flag.
# Built from parts so this file contains no literal the sweep would match, which
# is what let the previous version flag its own source.
_VERB = "docker" + r"\s+rm"
_DOCKER_RM = re.compile(_VERB + r"\b((?:\s+-[\w-]+)*)")

# Backtick-quoted occurrences are prose. with_test_postgres.sh explains this very
# fix in a comment that names the wrong form, and a gate that cannot tell a
# command from its own rationale fails on the commit that documents it.
_BACKTICKED = re.compile(r"`[^`]*" + _VERB + r"[^`]*`")

# Where the verb is a command rather than an argument list. Extensionless files
# are included for Makefile and hook scripts.
_SUFFIXES = {".sh", ".yml", ".yaml", ""}


def _swept_files() -> list[Path]:
    out = subprocess.run(
        ["git", "-C", str(_REPO), "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    ).stdout
    return [
        _REPO / rel
        for rel in out.split("\0")
        if rel and (_REPO / rel).suffix in _SUFFIXES and (_REPO / rel).is_file()
    ]


def _offenders_in(text: str) -> list[tuple[int, str]]:
    found = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        prose = [m.span() for m in _BACKTICKED.finditer(line)]
        for match in _DOCKER_RM.finditer(line):
            if any(lo <= match.start() < hi for lo, hi in prose):
                continue
            flags = match.group(1).split()
            if "-v" in flags or "--volumes" in flags:
                continue
            # `-fv` and friends: any short cluster containing v counts.
            if any(
                f.startswith("-") and not f.startswith("--") and "v" in f[1:]
                for f in flags
            ):
                continue
            found.append((lineno, stripped))
    return found


def test_every_container_removal_takes_the_volumes_flag() -> None:
    offenders: list[str] = []
    swept = 0
    for path in _swept_files():
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        swept += 1
        for lineno, line in _offenders_in(text):
            offenders.append(f"{path.relative_to(_REPO)}:{lineno}: {line}")

    assert swept > 0, "swept nothing: the file enumeration is broken, not clean"
    assert not offenders, (
        "container removal without the volumes flag leaks one anonymous volume "
        "per run:\n  " + "\n  ".join(offenders)
    )


def test_the_sweep_actually_matches_the_shape_it_hunts() -> None:
    """Both directions, so the matcher cannot pass by never matching anything."""
    leaky = 'docker' + ' rm -f "$name"'
    fixed = 'docker' + ' rm -f -v "$name"'
    clustered = 'docker' + ' rm -fv "$name"'
    assert _offenders_in(leaky), "the leaking form must be caught"
    assert not _offenders_in(fixed), "the fixed form must pass"
    assert not _offenders_in(clustered), "a -fv cluster must count as having -v"


def test_prose_skip_does_not_swallow_a_real_call() -> None:
    """The backtick rule is the kind of exemption that quietly widens until the
    sweep passes on anything. Pin both sides of it."""
    prose = "see `" + "docker" + " rm` for why"
    call = 'docker' + ' rm -f "$name"'
    assert not _offenders_in(prose), "backticked prose must be treated as prose"
    assert _offenders_in(call), "an unquoted call must NOT be treated as prose"
    mixed = 'docker' + ' rm -f "$n"  ; see `' + 'docker' + ' rm` above'
    assert _offenders_in(mixed), "a real call beside prose must still be caught"


def test_the_quality_gate_helper_is_still_a_call_site() -> None:
    """A negative control for the sweep: if with_test_postgres.sh stops removing
    its container, the sweep passes by having nothing to check and this guard has
    quietly stopped guarding anything."""
    helper = (_REPO / "scripts" / "with_test_postgres.sh").read_text()
    calls = [
        line.strip()
        for line in helper.splitlines()
        if _DOCKER_RM.search(line) and not line.strip().startswith("#")
    ]
    assert calls, "with_test_postgres.sh no longer removes its container at all"
    assert all("-v" in c for c in calls), calls
