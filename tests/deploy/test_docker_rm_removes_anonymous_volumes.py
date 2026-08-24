"""Every `docker rm` in this repo must pass `-v`, or it bills the host per run.

`docker run --rm` cleans up a container's anonymous volumes when the container
exits. A cleanup trap that calls `docker rm` FIRST pre-empts that, and
`docker rm` without `-v` keeps the anonymous volume. The container is gone, so
nothing points at the volume and nothing will ever collect it.

Measured on the beelink, 2026-08-24, with the pinned pgvector image the quality
gate uses:

    docker rm -f    <container>   ->  dangling volumes 4 -> 5   (leaked 1)
    docker rm -f -v <container>   ->  dangling volumes 5 -> 5   (leaked 0)

`scripts/with_test_postgres.sh` had the first form, so every green quality-gate
run left a ~180MB PostgreSQL data directory behind. Eleven days of runs had
accumulated 138 of them (16.7GB), which is most of what took that box to 88%,
and the same class of pressure that took the production host to 100% and aborted
the v0.4.47 roll mid-flight.

`-v` is safe to require everywhere: it removes only ANONYMOUS volumes attached
to the named container. Named volumes are never touched by it, so there is no
case where omitting it is the correct choice.

This reads the shipped scripts rather than the one that was fixed, so a NEW
leaking call added anywhere fails here instead of being found by a full disk.
"""

from __future__ import annotations

from pathlib import Path
import re
import subprocess


_REPO = Path(__file__).resolve().parents[2]

# `docker rm` with its flags, up to the first argument that is not a flag.
_DOCKER_RM = re.compile(r"docker\s+rm\b((?:\s+-[\w-]+)*)")

_SUFFIXES = {".sh", ".py", ".yml", ".yaml", ""}


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "-C", str(_REPO), "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    ).stdout
    paths = []
    for rel in out.split("\0"):
        if not rel:
            continue
        p = _REPO / rel
        if p.suffix in _SUFFIXES and p.is_file():
            paths.append(p)
    return paths


def test_every_docker_rm_passes_dash_v() -> None:
    offenders: list[str] = []
    for path in _tracked_files():
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        if "docker rm" not in text:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            # A comment quoting the wrong form is documentation, not a call. The
            # fix for this very leak explains itself in comments, so a check that
            # cannot tell the two apart would flag its own rationale.
            if stripped.startswith("#"):
                continue
            for match in _DOCKER_RM.finditer(line):
                flags = match.group(1).split()
                if "-v" in flags or "--volumes" in flags:
                    continue
                # `-fv` and friends: any short cluster containing v counts.
                if any(
                    f.startswith("-")
                    and not f.startswith("--")
                    and "v" in f[1:]
                    for f in flags
                ):
                    continue
                rel = path.relative_to(_REPO)
                offenders.append(f"{rel}:{lineno}: {stripped}")

    assert not offenders, (
        "`docker rm` without `-v` leaks one anonymous volume per run:\n  "
        + "\n  ".join(offenders)
    )


def test_the_quality_gate_helper_is_the_shape_we_fixed() -> None:
    """A negative control for the sweep above: if `with_test_postgres.sh` stops
    calling `docker rm` at all, the sweep passes vacuously and the guard has
    quietly stopped guarding anything."""
    helper = (_REPO / "scripts" / "with_test_postgres.sh").read_text()
    calls = [
        line.strip()
        for line in helper.splitlines()
        if "docker rm" in line and not line.strip().startswith("#")
    ]
    assert calls, "with_test_postgres.sh no longer removes its container at all"
    assert all("-v" in call for call in calls), calls
