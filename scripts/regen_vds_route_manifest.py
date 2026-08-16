#!/usr/bin/env python3
"""Rebind ``vds-route-manifest.json`` to the capture it witnesses.

THE STAGE THAT WAS MISSING. A console-parity recapture has four stages:

    1. capture-current.mjs --evidence   shipped/ + capture-manifest.json
    2. compare-current.py               diff/ + metrics.json
    3. THIS                             vds-route-manifest.json
    4. vds ledger screens / routes      .vds/ledgers/*.yaml

Stages 1, 2 and 4 are in the repo. Stage 3 was not, yet every recapture commit
in the history updated this file -- so it was being produced by hand or by
something that did not travel. Doing it by hand is a poor idea: the file
witnesses two other files by digest AND witnesses itself, so a single mistyped
character produces a manifest that passes casual reading and fails the gate with
a message about staleness rather than about typing.

WHAT IS DERIVED, AND WHAT IS NOT. Only three fields are rewritten:

    source         the capture-manifest and metrics pair, each by sha256
    takenAt        the capture's own capturedAt
    contentDigest  a digest over every other key

Everything else -- ``routes`` and ``doesNotCover`` above all -- is a GOVERNANCE
DECLARATION about what this parity programme does and does not cover. It is not
derivable from a screenshot and is deliberately carried through untouched.

``takenAt`` does track the capture, which is a small departure from the last
recapture commit (8b7a586d left it alone). Left alone it would have said
2026-08-15T18:09:06Z while witnessing a capture taken hours later -- a manifest
claiming to describe a capture that no longer exists is the exact failure this
whole gate is about.

STAGE 1 DELETES THIS FILE. capture-current.mjs rewrites current/ and removes
what it does not own, this file included. So when it is absent the previous
version is recovered from git to carry the declarations forward, rather than
inventing them.

    python3 scripts/regen_vds_route_manifest.py [--evidence-root DIR] [--check]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vds_ledger_support import value_digest  # noqa: E402  (after sys.path)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = REPO_ROOT / "docs/design/evidence/2026-08-11-console-parity/current"

# Mirrors ROUTE_KEYS in scripts/check_vds_ledgers.py. The digest is taken over
# every key EXCEPT contentDigest, which is the digest itself.
DIGESTED_KEYS = {"schemaVersion", "generatedBy", "takenAt", "source", "routes",
                 "doesNotCover"}


def sha256_of(path: Path) -> str:
    import hashlib
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_timestamp(value: str) -> str:
    """UTC, second resolution, trailing Z -- the one form VDS writes.

    capture-current.mjs emits milliseconds (2026-08-15T21:48:29.947Z) and `vds
    ledger routes` refuses that outright: "a timestamp whose form varies moves a
    digest without moving a fact". Since this field feeds contentDigest, a
    sub-second component would make two manifests describing the identical
    capture digest differently.
    """
    from datetime import datetime, timezone
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def previous_manifest(path: Path) -> dict:
    """The manifest as it stands, or as git last saw it.

    Stage 1 deletes this file, so "absent" is the ordinary case rather than an
    error -- but inventing the declarations it carries would not be.
    """
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    rel = path.relative_to(REPO_ROOT).as_posix()
    shown = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"HEAD:{rel}"],
        capture_output=True, text=True)
    if shown.returncode != 0:
        raise SystemExit(
            f"{rel} is absent from the working tree AND from HEAD.\n"
            "Its routes/doesNotCover declarations cannot be derived from a "
            "capture; recover the file before regenerating it.")
    return json.loads(shown.stdout)


def rebuild(root: Path) -> tuple[dict, dict]:
    capture_path = root / "capture-manifest.json"
    metrics_path = root / "metrics.json"
    manifest_path = root / "vds-route-manifest.json"

    # Fail loudly rather than emit a manifest witnessing files that are not
    # there: a digest of nothing is still a well-formed digest.
    missing = [p.name for p in (capture_path, metrics_path) if not p.exists()]
    if missing:
        raise SystemExit(
            f"cannot regenerate: {', '.join(missing)} missing from {root}.\n"
            "Run capture-current.mjs --evidence then compare-current.py first.")

    before = previous_manifest(manifest_path)
    capture = json.loads(capture_path.read_text(encoding="utf-8"))

    after = dict(before)                       # preserves key order
    after["source"] = (
        f"{capture_path.relative_to(REPO_ROOT).as_posix()} ({sha256_of(capture_path)}) "
        f"and metrics.json ({sha256_of(metrics_path)})"
    )
    captured_at = capture.get("capturedAt")
    if captured_at:
        after["takenAt"] = canonical_timestamp(captured_at)
    after["contentDigest"] = value_digest(
        {k: v for k, v in after.items() if k in DIGESTED_KEYS})
    return before, after


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--evidence-root", default=str(DEFAULT_ROOT))
    ap.add_argument("--check", action="store_true",
                    help="report whether it is already current; write nothing")
    args = ap.parse_args()

    root = Path(args.evidence_root).resolve()
    before, after = rebuild(root)
    path = root / "vds-route-manifest.json"

    if args.check:
        current = path.exists() and before == after
        print("current" if current else "STALE")
        return 0 if current else 1

    path.write_text(json.dumps(after, indent=2) + "\n", encoding="utf-8")
    changed = [k for k in after if before.get(k) != after[k]]
    print(f"  wrote {path.relative_to(REPO_ROOT)}")
    print(f"  rebound: {', '.join(changed) if changed else '(already current)'}")
    print(f"  takenAt: {after['takenAt']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
