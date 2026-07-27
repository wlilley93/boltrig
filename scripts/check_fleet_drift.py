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
# A service under `profiles:` is OPT-IN - compose does not start it unless the
# profile is selected, so its absence is the design, not drift. Without this the
# check reports vllm-openai and signal-cli-rest-api missing on every healthy box,
# goes permanently red, and gets ignored - the precise failure this file's own
# docstring warns about.
_SERVICE = re.compile(r"^  (?P<name>[a-z0-9][\w-]*):\s*$", re.MULTILINE)
_PROFILES = re.compile(r"^    profiles:\s*\[(?P<list>[^\]]*)\]", re.MULTILINE)


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
            _record_profiles(text)
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


# image-name -> True when the service carrying it is opt-in behind a profile.
_OPT_IN: dict[str, bool] = {}


def _record_profiles(text: str) -> None:
    """Note which services are profile-gated, keyed by their image name."""
    services = list(_SERVICE.finditer(text))
    for i, match in enumerate(services):
        end = services[i + 1].start() if i + 1 < len(services) else len(text)
        block = text[match.start():end]
        image = _IMAGE.search(block)
        if not image:
            continue
        name = image.group("ref").strip("\"'").split("@")[0].split("/")[-1].split(":")[0]
        # Only ever turn opt-in ON: an overlay that re-declares a service without
        # repeating `profiles:` must not silently make it look mandatory.
        if _PROFILES.search(block):
            _OPT_IN[name] = True
        else:
            _OPT_IN.setdefault(name, False)


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



def bind_mounted_repos(host: str, project: str) -> dict[str, tuple[str, str, int]]:
    """Git checkouts bind-mounted into running containers, and how stale each is.

    THE HALF A DIGEST PIN CANNOT SEE. Every image above is digest-pinned, which is
    exactly why this was invisible: on 2026-07-27 `app.boltrig.io` was serving a
    digest-pinned kernel while bind-mounting `libraries/` from a checkout of main
    that was FIFTY-SEVEN COMMITS BEHIND. A merged fix to the opbox skill - whose
    eight tool_grants named the kernel door's noun-first verbs while the tenant
    runs the frontend door's verb-first ones, so ZERO of them resolved - sat
    undelivered for three days and only landed because an unrelated retirement
    happened to pull that tree.

    A bind-mounted directory is a DEPLOYMENT SURFACE exactly like an image tag.
    `git pull` on it is a deploy step, and until this check existed it appeared in
    no runbook and no gate.

    STALENESS IS SCOPED TO THE MOUNTED PATH, not the tree. `HEAD..origin/main` on
    the whole checkout is red the moment anything merges, which would make this
    permanently red and therefore ignored - the cry-wolf failure that `gate-status`
    had on the same day. What matters is whether the BYTES THE CONTAINER READS are
    behind, so the count is `rev-list HEAD..origin/<branch> -- <mounted path>`. Ten
    commits behind with none of them touching `libraries/` is not a stale deploy;
    one commit behind that touches it is.

    Reported per (container, mounted path). A path that is not a git repository is
    reported too, because a copy nobody can update from source is the worse case.
    """
    script = (
        "for c in $(docker ps -q --filter "
        f"label=com.docker.compose.project={shlex.quote(project)}); do "
        """docker inspect -f '{{$n := .Name}}{{range .Mounts}}{{if eq .Type "bind"}}"""
        """{{$n}} {{.Source}}{{println}}{{end}}{{end}}' "$c"; done | sort -u | """
        "while read -r name src; do "
        "  [ -n \"$src\" ] || continue; "
        "  d=$src; [ -d \"$d\" ] || d=$(dirname \"$src\"); "
        "  top=$(git -C \"$d\" rev-parse --show-toplevel 2>/dev/null) || continue; "
        "  git -C \"$top\" fetch -q origin 2>/dev/null; "
        # A DETACHED head reports the literal string "HEAD", which would then be
        # compared against `origin/HEAD` and quietly produce a number about the
        # wrong ref. A deployment tree not on a branch is itself the finding, so
        # it is reported as such rather than measured.
        "  br=$(git -C \"$top\" rev-parse --abbrev-ref HEAD 2>/dev/null); "
        "  [ \"$br\" = HEAD ] && { echo \"$name|$src|DETACHED|$(git -C \"$top\" rev-parse --short HEAD)|-2\"; continue; }; "
        "  head=$(git -C \"$top\" rev-parse --short HEAD 2>/dev/null); "
        # The mounted path RELATIVE to the checkout, so the count is about the
        # bytes this container reads rather than about the repository.
        "  rel=${src#\"$top\"/}; [ \"$rel\" = \"$src\" ] && rel=.; "
        "  behind=$(git -C \"$top\" rev-list --count HEAD..origin/\"$br\" -- \"$rel\" 2>/dev/null || echo -1); "
        "  echo \"$name|$src|$br|$head|$behind\"; "
        "done"
    )
    try:
        proc = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=15", host, script],
            capture_output=True, text=True, timeout=180, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"NOT CHECKED: cannot read bind mounts on {host} ({exc})", file=sys.stderr)
        raise SystemExit(2) from exc

    out: dict[str, tuple[str, str, int]] = {}
    for line in proc.stdout.splitlines():
        parts = line.strip().split("|")
        if len(parts) != 5:
            continue
        name, mount, branch, head, behind = parts
        try:
            n = int(behind)
        except ValueError:
            n = -1
        # One entry per (container, MOUNT). Two paths from one checkout are two
        # facts, because they go stale independently: `libraries/` can be behind
        # while `boltrig/store/schema.sql` is current.
        out[f"{name.lstrip('/')}:{mount}"] = (branch, head, n)
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
            if _OPT_IN.get(name):
                print(f"  {name:16} not enabled   (profile-gated, absent by design)")
                continue
            missing.append(name)
            print(f"  {name:16} NOT RUNNING   pinned {digest[:19]}...")
        elif actual == digest:
            print(f"  {name:16} ok            {digest[:19]}...")
        else:
            drift.append((name, digest, actual))
            print(f"  {name:16} DRIFTED       pinned {digest[:19]}... "
                  f"running {actual[:19]}...")
    print("-" * 76)

    # The half a digest pin cannot see: a bind-mounted git checkout is a
    # deployment surface, and nothing above would notice it going stale.
    trees = bind_mounted_repos(args.host, args.project)
    stale: list[tuple[str, str, str, int]] = []
    if trees:
        print("\nBind-mounted git trees (a `git pull` here IS a deploy step)")
        print("-" * 76)
        for key, (branch, head, behind) in sorted(trees.items()):
            container, mount = key.split(":", 1)
            if behind == -2:
                print(f"  {container:22} {mount}")
                print(f"  {'':22}   DETACHED    not on a branch, at {head}")
                stale.append((container, mount, branch, behind))
            elif behind < 0:
                print(f"  {container:22} {mount}")
                print(f"  {'':22}   UNKNOWN     no upstream for {branch}")
                stale.append((container, mount, branch, behind))
            elif behind == 0:
                print(f"  {container:22} {mount}")
                print(f"  {'':22}   ok          {branch}@{head}, this path is current")
            else:
                print(f"  {container:22} {mount}")
                print(f"  {'':22}   STALE       {branch}@{head}, {behind} commit(s) "
                      f"touching this path are unpulled")
                stale.append((container, mount, branch, behind))
        print("-" * 76)

    if drift:
        print("\nDRIFT: the next `up -d` will swap the running image for the pinned one.")
        for name, want_d, got in drift:
            print(f"  - {name}: pinned {want_d}\n      running {got}")
        return 1
    if missing:
        # These are NOT profile-gated, so absence means a service that should be up
        # is not - which is not agreement, and does not get a silent pass.
        print(f"\nNOT RUNNING (pinned, not profile-gated, absent): {', '.join(missing)}")
        return 1
    if stale:
        print("\nSTALE BIND MOUNT: a container is serving files from a checkout that "
              "is behind its\nupstream. Digest pinning does nothing for these - the "
              "bytes come from the host\nfilesystem, so the fix is `git pull` in the "
              "tree, and that is a DEPLOY.")
        for container, mount, branch, behind in stale:
            how = ("on a DETACHED HEAD - a deployment tree must track a branch"
                   if behind == -2 else
                   "no upstream" if behind < 0
                   else f"{behind} unpulled commit(s) touch it on origin/{branch}")
            print(f"  - {container}: {mount} ({how})")
        return 1
    print("\nRESULT: PASS - every pinned image is the one running, and every "
          "bind-mounted tree is level with its upstream.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
