"""Hermetic regression tests for the disk-hygiene retention ladder.

WHY THIS FILE EXISTS. On 2026-08-23 `docker-disk-hygiene.sh` ran on the
production host at 03:17, reclaimed nothing (89% -> 89%), and wrote

    docker-disk-hygiene STILL 89% after pruning; reclaimable images are not the
    cause

directly above its own `docker system df` reporting **80.89GB of images
reclaimable**. Both halves were broken:

  * `--filter until=168h` bounds the AGE of what it removes, while the release
    cadence sets the VOLUME. Fifteen releases in four days meant every untagged
    image was newer than the window, so the window protected exactly the garbage
    it exists to remove.
  * the closing message asserted a conclusion the script never tested, and
    pointed the reader away from the real cause on the one run it mattered.

Six hours later the host hit 100% and a client tenant's UI crash-looped on
`No space left on device` mid-roll.

The stubs below never call Docker. `df` is driven by a file the fake `docker`
rewrites, so "the prune actually freed space" is modelled rather than assumed -
that is what lets the second test prove escalation STOPS as well as starts.
"""

from __future__ import annotations

from pathlib import Path
import subprocess


_REPO = Path(__file__).resolve().parents[2]
_HYGIENE = _REPO / "scripts" / "docker-disk-hygiene.sh"


def _write(path: Path, body: str) -> None:
    path.write_text(f"#!/usr/bin/env bash\nset -uo pipefail\n{body}\n")
    path.chmod(0o755)


def _harness(tmp_path: Path, *, reclaimable: str = "80.89GB",
             frees_at: str = "") -> tuple[Path, Path, Path]:
    """Build fake df/docker. `frees_at` is a window (e.g. '72') after whose
    prune the disk is modelled as dropping to 60%."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    pct_file = tmp_path / "pct"
    pct_file.write_text("89\n")
    log = tmp_path / "docker.log"
    log.write_text("")

    # `df --output=pcent` and `df -h --output=avail` are the only two forms used.
    _write(
        fake_bin / "df",
        f'''
if [[ "$*" == *"avail"* ]]; then
    echo "Avail"; echo "17G"; exit 0
fi
echo "Use%"
echo "$(cat {pct_file})%"
''',
    )

    # EXPLICIT exits, never a bare test relying on `set -e`: bash 3.2 (still
    # shipped by macOS) and bash 5.x disagree about a bare `[[ ]]` mid-script,
    # which is exactly how a stub stops injecting the behaviour it was written
    # for while the test keeps "passing". See test_backup_scripts.py.
    frees_clause = ""
    if frees_at:
        frees_clause = f'''
if [[ "$*" == *"until={frees_at}h"* ]]; then
    echo "60" > {pct_file}
fi
'''
    _write(
        fake_bin / "docker",
        f'''
echo "$*" >> {log}
if [[ "$*" == *"system df"* ]]; then
    echo "Images|{reclaimable}"
    echo "Containers|0B"
    # DELIBERATELY LONGER THAN A PIPE BUFFER. A consumer that stops reading after
    # the Images line leaves this producer writing into a closed pipe, so it takes
    # SIGPIPE and returns 141, and `set -o pipefail` turns that into the script
    # dying with the diagnostic unprinted. Real `docker system df` emits ~5 short
    # lines, which FIT the buffer, so the bug survived CI and one local package
    # run before showing up. Padding here makes the failure deterministic instead
    # of a race that passes most of the time.
    for i in $(seq 1 400); do echo "Filler$i|0B"; done
    exit 0
fi
{frees_clause}
exit 0
''',
    )
    return fake_bin, log, pct_file


def _run(fake_bin: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "HOME": str(tmp_path),
    }
    return subprocess.run(
        ["bash", str(_HYGIENE)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def _windows(log: Path) -> list[str]:
    """Retention windows actually attempted, in order."""
    out = []
    for line in log.read_text().splitlines():
        if "until=" in line:
            out.append(line.split("until=", 1)[1].split("h", 1)[0])
    return out


def test_escalates_when_the_window_protects_the_garbage(tmp_path: Path) -> None:
    """The 2026-08-23 shape: nothing is older than 168h, disk never drops."""
    fake_bin, log, _ = _harness(tmp_path)
    result = _run(fake_bin, tmp_path)

    assert _windows(log) == ["168", "72", "24", "6"], (
        f"expected the full ladder, got {_windows(log)}"
    )
    # Still over at the end, so cron must be told.
    assert result.returncode == 1


def test_stops_escalating_once_under_threshold(tmp_path: Path) -> None:
    """Escalation is a ladder, not a scorched-earth sweep: the shorter windows
    cost rollback targets, so they must not run once the disk is healthy."""
    fake_bin, log, _ = _harness(tmp_path, frees_at="72")
    result = _run(fake_bin, tmp_path)

    assert _windows(log) == ["168", "72"], (
        f"escalation ran past the point it was needed: {_windows(log)}"
    )
    assert "24" not in _windows(log)
    assert result.returncode == 0


def test_reports_remaining_reclaimable_instead_of_denying_it(tmp_path: Path) -> None:
    """The regression proper. The old text is a claim about a number the script
    had not read; asserting its absence is what keeps it from coming back."""
    fake_bin, _, _ = _harness(tmp_path, reclaimable="80.89GB")
    result = _run(fake_bin, tmp_path)

    assert "reclaimable images are not the cause" not in result.stderr
    assert "80.89GB" in result.stderr
    assert "STILL 89%" in result.stderr


def test_says_so_when_images_really_are_not_the_cause(tmp_path: Path) -> None:
    """The other branch must still be reachable, or the fix has only swapped one
    unconditional message for another."""
    fake_bin, _, _ = _harness(tmp_path, reclaimable="0B")
    result = _run(fake_bin, tmp_path)

    assert "outside Docker images" in result.stderr
    assert result.returncode == 1
    # 141 is SIGPIPE reaching this script through pipefail. Naming it separately
    # from "wrong message" keeps a silent death from reading as a content bug.
    assert result.returncode != 141, "the reporting path died on SIGPIPE"
