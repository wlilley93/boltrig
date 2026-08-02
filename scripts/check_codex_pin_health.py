#!/usr/bin/env python3
"""Is the pinned Codex binary SATISFIABLE on this box, and what is installed beside it?

WHY THIS EXISTS, and the failure it prevents. `codex_cell_policy.verify` already hashes the
binary and refuses a digest that is not the reviewed pin. That check is correct and is not
duplicated here, because it answers a different question at a different time: it asks "is the
binary I am about to exec the reviewed one?", at cell start, when a cell is already being
spawned. It cannot tell anyone, in advance, that the pinned binary is no longer on the machine
at all. That failure surfaces as a cell that will not start, at the moment someone wanted a
cell.

The pinned artefact lives at
`~/.codex/packages/standalone/releases/<version>-<target>/bin/codex`, which is a CACHE
DIRECTORY under a dot-directory. Nothing in this repository references that path except a
proposal document. On 2026-08-02 a cache-clearing sweep on this box removed several gigabytes
from neighbouring cache trees; it did not touch this one, but nothing would have stopped it,
and nothing would have reported it afterwards.

WHAT IS FATAL AND WHAT IS ONLY REPORTED, deliberately split.

  FATAL, but only when `BOLTRIG_CODEX_BINARY` is SET. That variable is how the composition
  root resolves the binary (`boltrig/config/settings.py:119`), so when it is set this box
  intends to run cells, and a missing or wrong-digest binary is a live fault. This mirrors
  `codex_cell_policy`'s conditions (regular file, not group- or world-writable, digest equals
  the pin) so the two cannot come to disagree.

  NOT FATAL when the variable is UNSET. A developer box that never spawns a cell is not
  broken, and a check that cannot pass on an ordinary checkout is a check people learn to
  skip. Instead the pin's SATISFIABILITY is reported: is there any binary on this box whose
  digest equals the pin? That is the question an operator actually needs answered before
  deploying, and it is answered by measurement rather than by reading a version string.

  NEVER FATAL: version drift between the pin and whatever `codex` is on PATH. Drift is a fact
  to know, not a fault. The operator seat is expected to run a newer CLI than the fleet pins,
  and making that red would break every developer box on the day someone ran `npm -g update`.
  It is printed because until this script existed, nothing on the estate reported it and the
  gap was rediscovered by hand.

WHAT THIS DOES NOT CLAIM. It does not verify the protocol schemas (that is
`check_codex_protocol.py`), it does not prove the sandbox engages (that is
`codex_sandbox_engagement.py`), and it does not check the binary a REMOTE box holds. It
answers one question about this machine.

Exit 0 clean, 1 on a fatal condition. Wired into `make check`.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "boltrig" / "fleet" / "infrastructure" / "codex_cell_policy.py"
# The conventional install root for standalone releases. Used ONLY to answer "is the pin
# satisfiable", never to decide what boltrig will exec: that is BOLTRIG_CODEX_BINARY's job.
RELEASES = Path.home() / ".codex" / "packages" / "standalone" / "releases"


def _pin() -> tuple[str, str]:
    """Read the pin from the module that enforces it, never from a second copy.

    Two literals for one fact is how a pin and its checker come to disagree, so this parses
    the authority rather than restating it.
    """
    text = POLICY.read_text(encoding="utf-8")
    version = re.search(r'^CODEX_CLI_VERSION\s*=\s*"([^"]+)"', text, re.M)
    digest = re.search(r'^CODEX_CLI_SHA256\s*=\s*"([0-9a-f]{64})"', text, re.M)
    if not version or not digest:
        raise SystemExit(
            f"FATAL: could not read CODEX_CLI_VERSION / CODEX_CLI_SHA256 from "
            f"{POLICY.relative_to(ROOT)}. The pin is the thing this checks; if it cannot be "
            f"read, nothing was checked."
        )
    return version.group(1), digest.group(1)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def _installed_version() -> str:
    try:
        out = subprocess.run(
            ["codex", "--version"], capture_output=True, text=True, timeout=20
        )
        return (out.stdout or out.stderr).strip().splitlines()[0] if out.stdout or out.stderr else "unknown"
    except (OSError, subprocess.SubprocessError, IndexError):
        return "not on PATH"


def main() -> int:
    version, want = _pin()
    problems: list[str] = []
    print(f"Codex pin: {version}  sha256:{want[:12]}...{want[-8:]}")

    configured = os.environ.get("BOLTRIG_CODEX_BINARY") or ""
    if configured:
        binary = Path(configured)
        print(f"  BOLTRIG_CODEX_BINARY is set: {binary}")
        if not binary.is_file():
            problems.append(
                f"BOLTRIG_CODEX_BINARY points at {binary}, which is not a regular file. This "
                f"box intends to run cells and cannot: every cell spawn will fail."
            )
        else:
            mode = binary.stat().st_mode
            if mode & (stat.S_IWGRP | stat.S_IWOTH):
                problems.append(
                    f"{binary} is group- or world-writable, so the digest proves nothing about "
                    f"what will be executed. codex_cell_policy refuses this at cell start."
                )
            got = _sha256(binary)
            if got != want:
                problems.append(
                    f"{binary} hashes to {got[:16]}... but the pin is {want[:16]}.... A cell "
                    f"would be refused at spawn with 'digest does not match the reviewed pin'."
                )
            else:
                print("  digest MATCHES the pin")
    else:
        print("  BOLTRIG_CODEX_BINARY is unset: this box is not configured to spawn cells.")
        print("  Not a fault. Reporting whether the pin is SATISFIABLE here instead.")

    # Satisfiability, always reported. This is the question an operator needs before deploying,
    # and it is answered by hashing files rather than by trusting a directory name: a directory
    # called 0.144.3 that holds different bytes is exactly the case a version string misses.
    found: list[Path] = []
    if RELEASES.is_dir():
        for candidate in sorted(RELEASES.glob("*/bin/codex")):
            try:
                if candidate.is_file() and _sha256(candidate) == want:
                    found.append(candidate)
            except OSError:
                continue
    if found:
        for f in found:
            print(f"  pin is SATISFIABLE: {f}")
    else:
        where = RELEASES if RELEASES.is_dir() else f"{RELEASES} (absent)"
        print(
            f"  pin is NOT satisfiable from {where}: no binary there hashes to the pin. "
            f"If this box is meant to run cells, the pinned release must be restored."
        )

    installed = _installed_version()
    print(f"  `codex` on PATH: {installed}")
    if version not in installed:
        print(
            f"  DRIFT (reported, not a fault): the fleet pins {version} and this seat runs "
            f"{installed}. Expected on an operator box. It matters only if someone bumps the "
            f"pin: `multi_agent_v1`, the sole namespace the tool ceiling admits, does not "
            f"exist in the 0.146 line, and schemas/codex/ holds {version} only."
        )

    if problems:
        print("\nCODEX PIN HEALTH: FAILED", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print("OK: the Codex pin is coherent on this box.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
