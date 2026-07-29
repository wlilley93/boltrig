#!/usr/bin/env python3
"""Make every path a COMMIT MESSAGE cites resolve. The third instance of a class.

check_prose_references.py makes references resolve in prose - source comments,
docs, orders. It cannot see a commit message, and a commit message is where this
project keeps saying which authority a change rests on:

    Refs: PERMIT-1785318255, docs/proposals/DEV-POSTURE-001-draft.yaml

That trailer, on 881a9df, cites a file that exists nowhere. Not moved, not
renamed: it was never committed. A First Instance court searched origin/main, the
working tree and `git log --all --diff-filter=A` for it, found nothing, and
recorded the finding as the THIRD instance of one defect class:

  1. INV-8, cited as the authority for a control, with zero occurrences anywhere
     in the repository.
  2. The C1-C9 incident: an order whose conditions cited numbered items that did
     not exist, so the conditions could not be checked against anything.
  3. DEV-POSTURE-001-draft.yaml, above - committed ONE commit-cluster after the
     court that named the class.

The shape is always the same and it is not a typo. A change is justified by
pointing at a document, the pointer is never followed, and the justification is
therefore unfalsifiable. It is the same failure as a test that cannot fail: the
record LOOKS like it rests on something.

So this gate closes the surface prose cannot reach. It is the forward-looking half
of [2026] VJS-CC-BOLTRIG-DEVELOPMENT-POSTURE-001 D8; the historical half is
immutable (a commit message cannot be edited) and is recorded instead, in that
gate's ALLOW and in the order's own reasoning.

WHAT IT CHECKS. Every commit reachable from the ref under examination, for
trailer lines beginning `Refs:` / `Ref:` / `See:`. Each repo-relative path on
such a line must exist in that commit's OWN tree - not at HEAD. That distinction
is deliberate and it is the whole difference between a useful gate and a false
one: a commit may legitimately cite a file that has since been deleted, and
judging history by today's tree would turn every honest deletion into a
violation. What is refused is a commit that cited something which did not exist
WHEN IT WAS WRITTEN.

Non-paths are ignored on purpose: PERMIT-*, order ids, issue numbers and bare
words are not repository paths and this gate has no business guessing at them.
A token counts as a path only if it contains a "/" and a file extension.

WHY IT IS NOT A RATCHET. Measured on origin/main when written: 8 commits carry a
Refs: trailer and exactly 1 dangles - the one the court named. One known offender
in an immutable record is an ALLOW entry with a reason, not a numeric baseline to
creep upward. A count would let the second offender hide inside a bumped number.

Usage:
    python scripts/check_commit_trailers.py                 # HEAD
    python scripts/check_commit_trailers.py --ref origin/main
    python scripts/check_commit_trailers.py --limit 200
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

# A token is a candidate path only with BOTH a separator and an extension.
# Without the "/" requirement this matches "e.g." and every abbreviation in a
# commit message; without the extension it matches "docs" and "PERMIT-123".
_PATH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-/]*\.[A-Za-z0-9]{1,6}")
_TRAILER = re.compile(r"^\s*(refs?|see)\s*:", re.IGNORECASE)

# Paths a commit may cite that will never resolve, each with the reason. Held to
# the same bar as the order-binding waivers: a commit message is IMMUTABLE, so an
# entry here is a record of a finding, never permission to make a new one.
ALLOW: dict[tuple[str, str], str] = {
    (
        "881a9dfd",
        "docs/proposals/DEV-POSTURE-001-draft.yaml",
    ): (
        "THE FINDING THIS GATE EXISTS FOR, and the reason it cannot be cured: a commit "
        "message is immutable, so the citation stays wrong forever. "
        "[2026] VJS-CC-BOLTRIG-DEVELOPMENT-POSTURE-001 searched origin/main, the working "
        "tree and git log --all --diff-filter=A and found the draft nowhere - it was never "
        "committed - and recorded it as the THIRD instance of the dangling-authority class "
        "(INV-8, then C1-C9, then this), committed one commit-cluster after the court that "
        "named the class. Recorded, not waived away: this gate is that order's D8 cure, and "
        "the entry is the evidence it was needed."
    ),
}


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout


def cited_paths(body: str) -> list[str]:
    """The repo-relative paths cited on trailer lines in a commit message."""
    out: list[str] = []
    for line in body.splitlines():
        if not _TRAILER.match(line):
            continue
        _, _, rest = line.partition(":")
        out.extend(p for p in _PATH.findall(rest) if "/" in p)
    return out


def tree_at(sha: str) -> set[str]:
    """Every tracked path in ONE commit's own tree.

    Its own tree, never HEAD's: a commit may legitimately cite a file later
    deleted, and judging history by today's tree would report every honest
    deletion as a violation.
    """
    return set(_git("ls-tree", "-r", "--name-only", sha).splitlines())


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--limit", type=int, default=800)
    args = ap.parse_args()

    raw = _git(
        "log", "--format=%H%x00%s%x00%b%x1e", f"-{args.limit}", args.ref
    )
    entries = [e.strip() for e in raw.split("\x1e") if e.strip()]

    print(f"Commit trailer references ({args.ref}, {len(entries)} commits)")
    print("-" * 92)

    # TWO counters, because they answer different questions and conflating them
    # broke this gate's own selftest. `with_trailer` is "did the convention appear
    # at all", which is what the empty-scan refusal is about. `with_paths` is "did
    # anything need resolving". A trailer that cites only PERMIT-123 is a healthy
    # commit, not evidence the scan is broken.
    with_trailer = 0
    with_paths = 0
    problems: list[str] = []
    allowed_hits: list[str] = []

    for entry in entries:
        parts = entry.split("\x00")
        sha, subject, body = (parts + ["", ""])[:3]
        if not any(_TRAILER.match(line) for line in body.splitlines()):
            continue
        with_trailer += 1
        paths = cited_paths(body)
        if not paths:
            continue
        with_paths += 1
        tree = None
        for path in paths:
            key = (sha[:8], path)
            if key in ALLOW:
                allowed_hits.append(f"{sha[:8]} {path}")
                continue
            if tree is None:
                tree = tree_at(sha)
            if path not in tree:
                problems.append(
                    f"{sha[:8]}  {subject[:52]}\n"
                    f"      cites {path}, which did not exist in that commit's own tree"
                )

    if with_trailer == 0:
        # A gate that found nothing to check has not passed, it has failed to
        # run. Silence here means the log was unreadable or the trailer
        # convention changed, and reporting either as OK is the exact blindness
        # this file exists to end.
        print(
            f"FAIL: scanned {len(entries)} commits and found NO Refs:/See: trailer at all.\n"
            "      Either the log is truncated (a shallow clone) or the convention moved.\n"
            "      A scan with nothing to check is a broken scan, not a clean history.",
            file=sys.stderr,
        )
        return 1

    print(f"commits examined={len(entries)}  carrying a trailer={with_trailer}  "
          f"citing a path={with_paths}  allowed={len(allowed_hits)}  "
          f"unresolved={len(problems)}")
    for hit in allowed_hits:
        print(f"  allowed  {hit}")
    print()

    if problems:
        print("A COMMIT CITES A PATH THAT DID NOT EXIST WHEN IT WAS WRITTEN:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\n  A commit message is immutable, so this cannot be fixed after the fact.\n"
            "  Before pushing: add the file, or cite something that exists, or drop the\n"
            "  citation. A pointer nobody can follow makes the justification\n"
            "  unfalsifiable, which is the whole defect class.\n"
            "  If the reference is genuinely unresolvable, record it in ALLOW in this\n"
            "  script with the reason - as a finding, not as permission.",
            file=sys.stderr,
        )
        print("\nRESULT: FAIL - a commit rests on an authority that cannot be found.", file=sys.stderr)
        return 1

    print("RESULT: PASS - every path cited in a commit trailer existed when it was cited.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
