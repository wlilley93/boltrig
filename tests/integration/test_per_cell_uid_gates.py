"""The J7 and J9 live gates for per-cell uids ([2026] VJS-CC-VJS 7).

These are the two tests the court set as acceptance conditions, and it expressly
forbade discharging either "by argument or review or the absence of a known attack
rather than by the adversarial test itself" (VJS-CC-VJS 5, carried into J7 and
J9). A run I did once by hand is not that. These are.

They drive the REAL built image under the exact granted posture (uid 0,
``cap_drop: ALL``, ``cap_add: [SETUID, SETGID]``, ``no_new_privileges``,
``read_only``) with per-slot tmpfs mounts declared the way compose declares them.

**J7** spawns a cell through the real spawner and proves it cannot escalate: not
back to the spawner uid, not to the API uid, not sideways into a sibling's uid,
and not by exec'ing a setuid binary (there are none left, stripped at build under
J4).

**J9** is the gate that permits concurrent tenants at all. Two live cells, hostile
A holding full write access to everything its uid can reach, attacking cell B's
``config.toml`` by every route: rewrite, append, read, unlink, rename-over, chmod,
create-a-new-file, list, chown. All must be refused, and B must verify its own
``auth.command`` survived, because B is the only party that can read B's slot.

Opt-in, like the other live tests: they need docker and a built image, so they
skip loudly rather than pretend when either is absent. Set
BOLTRIG_PER_CELL_IMAGE to the image tag to arm them.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_IMAGE_ENV = "BOLTRIG_PER_CELL_IMAGE"
_PROBES = Path(__file__).parent / "percell"

_POSTURE = (
    "--user", "0:0",
    "--cap-drop", "ALL",
    "--cap-add", "SETUID",
    "--cap-add", "SETGID",
    "--security-opt", "no-new-privileges:true",
    "--read-only",
    "--tmpfs", "/tmp:mode=0777",
)


def _armed() -> bool:
    return bool(os.environ.get(_IMAGE_ENV)) and shutil.which("docker") is not None


def _run(mounts: tuple[str, ...], driver: str, extra: tuple[str, ...] = ()) -> str:
    command = [
        "docker", "run", "--rm", "-q",
        *mounts,
        "-e", "PYTHONPATH=/app",
        *_POSTURE,
        *extra,
        "--entrypoint", "/usr/local/bin/python3",
        os.environ[_IMAGE_ENV], "-u", driver,
    ]
    done = subprocess.run(command, capture_output=True, text=True, timeout=180)
    return done.stdout + done.stderr


def _mount(name: str, target: str) -> tuple[str, ...]:
    return ("-v", f"{(_PROBES / name).as_posix()}:{target}:ro")


pytestmark = pytest.mark.skipif(
    not _armed(),
    reason=f"requires docker and a built kernel image named by {_IMAGE_ENV}",
)


def test_j7_a_spawned_cell_cannot_escalate() -> None:
    """J7: every escalation route the court named, refused on the real image."""

    output = _run(
        _mount("j7_probe.py", "/probe.py") + _mount("j7_driver.py", "/driver.py"),
        "/driver.py",
    )
    assert "per-cell mode: True" in output, output
    for route in (
        "setuid(0) back to the spawner: refused",
        "setuid(10001) to the API: refused",
        "setuid(20002) sideways to a sibling: refused",
    ):
        assert route in output, output
    # su without its setuid bit cannot change uid; a ZERO exit would mean it did.
    assert "execve /usr/bin/su -> exit 1 (refused)" in output, output
    assert "CapPrm=0000000000000000" in output, output
    assert "NoNewPrivs=1" in output, output


def test_j9_a_hostile_cell_cannot_reach_a_siblings_config() -> None:
    """J9: THE gate. Two live cells; hostile A must not obtain B's bearer.

    Every refusal is asserted individually rather than by counting, so a future
    change that silently drops one route from the probe cannot pass by arithmetic.
    """

    mounts = (
        _mount("j9_victim.py", "/victim.py")
        + _mount("j9_attacker.py", "/attacker.py")
        + _mount("j9_driver.py", "/driver.py")
    )
    slots = (
        "--tmpfs", "/cells:mode=0755,uid=0,gid=0",
        "--tmpfs", "/cells/slot-0:mode=0700,uid=20001,gid=20001",
        "--tmpfs", "/cells/slot-1:mode=0700,uid=20002,gid=20002",
    )
    output = _run(mounts, "/driver.py", slots)

    assert "distinct: True" in output, output
    for vector in (
        "rewrite B's config.toml: refused",
        "append to B's config.toml: refused",
        "read B's config.toml: refused",
        "unlink B's config.toml: refused",
        "replace B's config.toml by rename: refused",
        "chmod B's config.toml: refused",
        "create a NEW file in B's slot: refused",
        "list B's slot: refused",
        "chown B's slot to itself: refused",
    ):
        assert vector in output, output

    # A cell owning its OWN slot is the design, not a breach.
    assert "write its OWN config.toml: succeeded (EXPECTED" in output, output
    # B is the only party that can read B's slot, so B is the only honest oracle.
    assert "config intact: True" in output, output
    assert "auth.command intact: True" in output, output
    # Even uid 0 is locked out, because cap_drop ALL removes CAP_DAC_OVERRIDE.
    assert "could list B's slot: refused, as expected" in output, output


def test_j1_wiring_the_dropped_api_routes_a_spawn_through_the_lane() -> None:
    """The PRODUCT path, which every green test hid until it was tested directly.

    The J9 gate proved the mechanism in a harness that stayed uid 0. The product
    decides per-cell mode inside the API, which the entrypoint DROPS to uid 10001,
    so per_cell_uid_mode_available read False there and nothing built a lane: the
    feature was enacted in compose and OFF in the product. This drives the real
    join - a dropped API sees per-cell mode from the inherited spawner socket,
    builds a CellLane, and routes a real spawn through it under a distinct uid.
    """

    output = _run(
        _mount("wiring_driver.py", "/driver.py"),
        "/driver.py",
        ("--tmpfs", "/tmp:mode=0777"),
    )
    assert "dropped API uid: 10001" in output, output
    assert "per_cell_uid_mode_available: True" in output, output
    assert "routed-through-the-lane" in output, output
