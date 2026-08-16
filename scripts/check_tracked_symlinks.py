#!/usr/bin/env python3
"""Refuse a tracked symlink that does not resolve to something inside the repo.

WHY THIS EXISTS. `.venv` was tracked on origin/main as a symlink pointing at
itself:

    .venv -> /path/to/boltrig/.venv                         # ELOOP

It reached main in 7c6153b (#177) and every clone taken since materialised it,
so `stat(".venv")` raised OSError 40 (Too many levels of symbolic links) on a
machine that had done nothing wrong. Nothing caught it, for two reasons worth
stating because both are general:

  1. .gitignore said `.venv/`, and a trailing slash matches a DIRECTORY. The
     thing added was a SYMLINK, which is not a directory, so the ignore rule
     never applied and `git add -A` took it. An ignore rule written for one
     filesystem object type is not a rule about the NAME.
  2. No gate looked at link targets at all. Every check in scripts/ reads file
     CONTENT; a symlink's content is its target string, and a 37-byte blob of
     path text passes a lint, a type-check and a test suite without comment.

WHAT IT REFUSES. Any tracked symlink (git mode 120000) whose target either

  - does not resolve at all (dangling, or a loop, like the case above), or
  - resolves OUTSIDE the repository root.

Both are about PORTABILITY, which is the actual property at stake: a repository
is a thing other machines check out. An absolute target, or one that climbs out
of the tree, is a statement about the author's filesystem and means nothing
anywhere else - and the loop above is only the most extreme case of that. A
relative link to a sibling file inside the tree is fine and stays fine.

Not a ratchet, and deliberately not: the measured count on origin/main when
written was ONE, and it was the defect. A numeric baseline would let a second
one hide inside a bumped number.

Usage:
    python scripts/check_tracked_symlinks.py
    python scripts/check_tracked_symlinks.py --root /path/to/checkout
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def tracked_symlinks(root: Path) -> list[str]:
    """Repo-relative paths git records with mode 120000, in one call."""
    out = subprocess.run(
        ["git", "ls-files", "-s"],
        cwd=root, capture_output=True, text=True, check=True,
    ).stdout
    links: list[str] = []
    for line in out.splitlines():
        meta, _, path = line.partition("\t")
        if meta.split(" ", 1)[0] == "120000":
            links.append(path)
    return links


def verdict(root: Path, rel: str) -> str | None:
    """The reason this link is refused, or None when it is fine.

    os.path.realpath(strict=False) is used rather than Path.resolve() because it
    returns a best-effort answer for a dangling target instead of raising, which
    lets the dangling and escaping cases be reported with the same code path.
    A LOOP is the one case realpath cannot answer, so it is tested first via
    stat(), which is exactly the call that failed on the .venv case.
    """
    link = root / rel
    try:
        target_text = os.readlink(link)
    except OSError as exc:  # the index says 120000 but the tree disagrees
        return f"git records it as a symlink but it cannot be read: {exc}"

    try:
        link.stat()  # follows the link; ELOOP and ENOENT both land here
    except OSError as exc:
        return f"points at {target_text!r}, which does not resolve: {exc.strerror}"

    resolved = Path(os.path.realpath(link, strict=False))
    try:
        resolved.relative_to(os.path.realpath(root))
    except ValueError:
        return (
            f"points at {target_text!r}, which resolves OUTSIDE the repository "
            f"({resolved}). That is a statement about one machine's filesystem, "
            "so it means nothing in any other checkout."
        )
    return None


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--root", default=None)
    args = ap.parse_args()

    root = Path(args.root) if args.root else Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    )

    links = tracked_symlinks(root)
    print(f"Tracked symlinks ({root})")
    print("-" * 92)
    print(f"tracked symlinks={len(links)}")

    problems = [(rel, why) for rel in links if (why := verdict(root, rel))]
    for rel in links:
        mark = "BAD " if any(rel == p for p, _ in problems) else "ok  "
        print(f"  {mark}{rel} -> {os.readlink(root / rel)}")
    print()

    if problems:
        print("A TRACKED SYMLINK DOES NOT SURVIVE A FRESH CLONE:", file=sys.stderr)
        for rel, why in problems:
            print(f"  - {rel}\n      {why}", file=sys.stderr)
        print(
            "\n  Remove it (git rm --cached <path>) and make sure .gitignore names it\n"
            "  WITHOUT a trailing slash, or the rule only covers the directory form and\n"
            "  a symlink of the same name slips straight back in - which is how the\n"
            "  .venv case happened. If a link is genuinely wanted, make it RELATIVE and\n"
            "  point it at something inside the tree.",
            file=sys.stderr,
        )
        print("\nRESULT: FAIL - a tracked symlink is not portable.", file=sys.stderr)
        return 1

    # Zero tracked symlinks is a real, healthy answer here, unlike the empty-scan
    # case in check_commit_trailers.py: `git ls-files -s` listing nothing at all
    # would mean an empty repository, and that cannot be mistaken for a pass.
    print("RESULT: PASS - every tracked symlink resolves inside the repository.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
