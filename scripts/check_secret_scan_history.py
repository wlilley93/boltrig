#!/usr/bin/env python3
"""Refuse a complete-history secret scan when Git objects are unavailable."""

from __future__ import annotations

import os
import subprocess
import sys


def revision_walk() -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    # A preflight must observe a partial clone, not silently hydrate it.  The
    # scanner runs in a read-only container and cannot perform that hydration.
    env["GIT_NO_LAZY_FETCH"] = "1"
    return subprocess.run(
        ["git", "rev-list", "--objects", "--all", "--missing=print"],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )


def missing_object_count(output: str) -> int:
    return sum(line.startswith("?") for line in output.splitlines())


def main() -> int:
    result = revision_walk()
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()
        suffix = f": {detail[-1]}" if detail else ""
        print(f"secret-scan history preflight failed{suffix}", file=sys.stderr)
        return 1
    missing = missing_object_count(result.stdout)
    if missing:
        print(
            "secret-scan refused: complete Git history is unavailable "
            f"({missing} promised object(s) missing). Hydrate the partial clone "
            "before scanning; a read-only scanner cannot fetch them.",
            file=sys.stderr,
        )
        return 1
    print("secret-scan history preflight: complete Git object graph available")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
