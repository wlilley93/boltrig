#!/usr/bin/env python3
"""Is what is RUNNING what we pinned? Ask the boxes, never assume.

GOAL-claims-must-be-load-bearing, criterion 4 ("config that is derived, not
restated") - its live half, and the last of the six criteria without a mechanism.

A compose override pinning an image the containers are not running is one of the
eleven original defects, and it is the nastiest kind: everything looks correct,
because the FILE is correct. The drift only surfaces at the next `up -d`, which
silently swaps the running image for the pinned one - a loaded gun, fired by an
unrelated deploy, at a time nobody chose.

This is deliberately NOT a CI gate and never can be. CI has no boxes; the claim
"tenant X runs digest Y" is only answerable by asking tenant X. So it is an
operator command, run before a deploy and after one.

THE NOT-CHECKED RULE. Where a host cannot be reached, this reports NOT CHECKED
and exits non-zero, rather than reporting agreement it did not observe. That
distinction is the whole point: `fleet-health` learned it the other way round
(green when it could not look, because a permanently-red probe gets ignored), and
the reasoning inverts here. A health probe that cannot look is usually an offline
dev box; a drift check that cannot look is an operator about to deploy blind.

Usage:
    python scripts/check_fleet_drift.py --host jellytot-prod \
        --compose ~/Projects/boltrig-main/docker-compose.yml \
        --overlay ~/Projects/opbox-prod/boltrig-tenants/boltrig-io.override.yml \
        --project boltrig
"""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys

# `image: repo:tag@sha256:...` - the digest is what actually identifies the build;
# the tag is a label anyone can move.
_IMAGE = re.compile(r"^\s*image:\s*(?P<ref>\S+)\s*$", re.MULTILINE)
_DIGEST = re.compile(r"@(sha256:[0-9a-f]{64})$")


def _read(path: str, host: str | None) -> str:
    """Read a compose file, from the HOST when one is given.

    The pins that matter are the ones on the box being deployed, not a copy in
    somebody's checkout - comparing a local file against a remote daemon would
    answer a question nobody asked and would go green while the box's own overlay
    said something else entirely.
    """
    if host is None:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    proc = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=15", host, f"cat {shlex.quote(path)}"],
        capture_output=True, text=True, timeout=120, check=False,
    )
    if proc.returncode != 0:
        print(f"NOT CHECKED: cannot read {path} on {host}: {proc.stderr.strip()}",
              file=sys.stderr)
        raise SystemExit(2)
    return proc.stdout


def pinned(paths: list[str], host: str | None = None) -> dict[str, str]:
    """Every first-party image pinned across the merged compose files.

    Later files win, which is how compose itself merges an overlay over a base -
    reading them in the other order would report the base's pin as authoritative
    and call a correctly-overridden tenant "drifted".
    """
    out: dict[str, str] = {}
    for path in paths:
        try:
            text = _read(path, host)
        except OSError as exc:
            print(f"fleet-drift: cannot read {path}: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        for match in _IMAGE.finditer(text):
            ref = match.group("ref").strip("\"'")
            digest = _DIGEST.search(ref)
            if not digest:
                continue  # unpinned or third-party: validate_release_compose's job
            name = ref.split("@")[0].split("/")[-1].split(":")[0]
            out[name] = digest.group(1)
    return out


def running(host: str, project: str) -> dict[str, str]:
    """The digest each container is ACTUALLY running, read from the daemon.

    `docker ps --format '{{.Image}}'` is NOT the thing to read and this used to
    read it: docker prints the tag there and drops the digest, so every service
    came back "unpinned at runtime" and the check was structurally incapable of
    ever agreeing. `.Config.Image` on the container is the reference it was
    CREATED from, digest intact, which is exactly what a compose pin is.
    """
    script = (
        "for c in $(docker ps -q --filter "
        f"label=com.docker.compose.project={shlex.quote(project)}); do "
        "docker inspect -f '{{.Name}} {{.Config.Image}}' \"$c\"; done"
    )
    try:
        proc = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=15", host, script],
            capture_output=True, text=True, timeout=120, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"NOT CHECKED: cannot reach {host} ({exc})", file=sys.stderr)
        raise SystemExit(2) from exc
    if proc.returncode != 0:
        print(f"NOT CHECKED: {host} refused the query: {proc.stderr.strip()}", file=sys.stderr)
        raise SystemExit(2)

    out: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        # A space, not a tab: an escaped \t does not survive the trip through ssh
        # and comes back as two literal characters, which silently matched nothing
        # and reported the whole fleet "not running".
        if " " not in line.strip():
            continue
        _, ref = line.strip().split(" ", 1)
        digest = _DIGEST.search(ref.strip())
        name = ref.strip().split("@")[0].split("/")[-1].split(":")[0]
        if digest:
            out[name] = digest.group(1)
        else:
            # A running container whose reference carries no digest cannot be
            # compared, and saying nothing about it would read as agreement.
            out[name] = "UNPINNED-AT-RUNTIME"
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--compose", required=True, action="append", dest="files")
    parser.add_argument("--overlay", action="append", dest="files")
    parser.add_argument("--local", action="store_true",
                        help="read the compose files locally instead of from --host")
    args = parser.parse_args()

    want = pinned(args.files, None if args.local else args.host)
    if not want:
        print("fleet-drift: no digest-pinned images found - refusing to report "
              "agreement, since a comparison against nothing always agrees",
              file=sys.stderr)
        return 1
    have = running(args.host, args.project)

    print(f"Pinned vs running: {args.host} / project={args.project}")
    print("-" * 76)
    drift, missing = [], []
    for name, digest in sorted(want.items()):
        actual = have.get(name)
        if actual is None:
            missing.append(name)
            print(f"  {name:16} NOT RUNNING   pinned {digest[:19]}...")
        elif actual == digest:
            print(f"  {name:16} ok            {digest[:19]}...")
        else:
            drift.append((name, digest, actual))
            print(f"  {name:16} DRIFTED       pinned {digest[:19]}... "
                  f"running {actual[:19]}...")
    print("-" * 76)

    if drift:
        print("\nDRIFT: the next `up -d` will swap the running image for the pinned one.")
        for name, want_d, got in drift:
            print(f"  - {name}: pinned {want_d}\n      running {got}")
        return 1
    if missing:
        # Not automatically wrong - a profile-gated service is legitimately absent -
        # but it is not agreement either, so it does not get a silent pass.
        print(f"\nNOT RUNNING (pinned but absent): {', '.join(missing)}")
        print("Confirm each is profile-gated rather than a service that died.")
        return 1
    print("\nRESULT: PASS - every pinned image is the one running.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
