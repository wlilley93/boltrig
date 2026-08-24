#!/usr/bin/env python3
"""Rewrite a citation's visible label to the repo-relative path its own link
target already names.

Authors wrote citations as `bootstrap.py:31`](../../../boltrig/api/bootstrap.py).
The link target is correct and unambiguous; the visible label is a bare
basename, and `bootstrap.py` alone matches four different real files in this
tree. This makes the label match the target.

This is a NOTATION fix and nothing else. It never invents a path, never changes
a line number, and never touches a citation whose derived target does not exist
on disk. It cannot make a false claim true, and it cannot make a true claim
false: it only makes the citation say which file it always meant.

Anchors are deliberately NOT generated here. An anchor auto-copied from the
cited line would make every citation self-consistent by construction, which
would turn the verifier into a check that cannot fail. Anchors are added by
re-reading, or not at all.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CORPUS = Path(__file__).resolve().parent
ROOT = CORPUS.parent.parent

# `LABEL:NN`](RELPATH)
CITE = re.compile(r"`([A-Za-z0-9_./-]+\.[A-Za-z0-9_]{1,12}):(\d+)`\]\(([^)]+)\)")


def repo_path(target: str) -> str | None:
    t = target.split("#")[0].strip()
    if t.startswith(("http://", "https://")):
        return None
    parts = [p for p in t.split("/") if p not in ("", ".")]
    while parts and parts[0] == "..":
        parts.pop(0)
    if not parts:
        return None
    cand = "/".join(parts)
    return cand if (ROOT / cand).is_file() else None


def main() -> int:
    apply = "--apply" in sys.argv
    changed_files = 0
    changed_cites = 0
    unresolved = 0

    for md in sorted(CORPUS.rglob("*.md")):
        if md.name in {"AUTHORING-CONTRACT.md"}:
            continue
        text = md.read_text()
        local = 0

        def sub(m: re.Match[str]) -> str:
            nonlocal local, unresolved
            label, line, target = m.group(1), m.group(2), m.group(3)
            real = repo_path(target)
            if real is None:
                unresolved += 1
                return m.group(0)
            if label == real:
                return m.group(0)
            local += 1
            return f"`{real}:{line}`]({target})"

        new = CITE.sub(sub, text)
        if local:
            changed_files += 1
            changed_cites += local
            if apply:
                md.write_text(new)
        if local:
            print(f"  {md.relative_to(CORPUS)}: {local} label(s) {'rewritten' if apply else 'would be rewritten'}")

    verb = "rewrote" if apply else "would rewrite"
    print(f"{verb} {changed_cites} citation label(s) across {changed_files} file(s); "
          f"{unresolved} link target(s) did not resolve to a file and were left alone")
    if not apply:
        print("dry run. pass --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
