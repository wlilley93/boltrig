#!/usr/bin/env python3
"""Move a citation's line number to where its own anchor actually is.

The anchor is text the author copied out of the file. If that exact text sits at
line 421 and the citation says 417, the citation is RIGHT about what it saw and
WRONG about where. Correcting the number is truth-preserving: it makes the
pointer agree with the quote the author already committed to.

Two hard limits keep this from becoming a machine that manufactures agreement:

  * An anchor found ZERO times in the file is never touched. That citation is
    making a claim the file does not support and a human or an agent has to look.
  * An anchor found MORE THAN ONCE is never touched. Which occurrence the author
    meant is a judgment, and this script does not make judgments.

Anchors are never invented, never edited, and never copied out of the source.
"""

from __future__ import annotations

import re
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# ONE definition of what a citation and an anchor are. This script used to keep
# its own copy, which drifted from the gate's: the two disagreed about where an
# anchor ended, so every run "relocated" the same 355 citations and the gate kept
# rejecting them. A rule stated twice is one rule and one disagreement.
_gate = SourceFileLoader("_gate", str(Path(__file__).resolve().parent / "verify-citations.py")).load_module()
CITE = _gate.CITE
ANCHOR = _gate.ANCHOR
BARE_CITE = _gate.BARE_CITE
LOOKAHEAD = _gate.LOOKAHEAD
WINDOW = _gate.WINDOW
unescape = _gate.unescape
CORPUS = _gate.CORPUS
ROOT = _gate.ROOT


def norm(s: str) -> str:
    return " ".join(s.split())


def main() -> int:
    apply = "--apply" in sys.argv
    moved = ambiguous = absent = fine = 0
    src_cache: dict[str, list[str]] = {}

    for md in sorted(CORPUS.rglob("*.md")):
        if md.name == "AUTHORING-CONTRACT.md":
            continue
        lines = md.read_text(errors="replace").splitlines()
        out = list(lines)
        touched = 0

        for i, line in enumerate(lines):
            new_line = line
            for m in reversed(list(CITE.finditer(line))):
                path, cited = m.group(1), int(m.group(2))
                target = ROOT / path
                if not target.is_file():
                    continue
                if path not in src_cache:
                    src_cache[path] = [norm(x) for x in target.read_text(errors="replace").splitlines()]
                src = src_cache[path]

                tail = " ".join([line[m.end():], *lines[i + 1:i + 1 + LOOKAHEAD]])
                needle = None
                for am in ANCHOR.finditer(tail):
                    cand = next(g for g in am.groups() if g is not None)
                    if BARE_CITE.fullmatch(cand.strip()):
                        break
                    needle = norm(unescape(cand))
                    break
                if needle is None:
                    continue

                hits = [k + 1 for k, hay in enumerate(src) if needle in hay]
                if hits == [cited]:
                    fine += 1
                    continue
                if len(hits) > 1:
                    near = [h for h in hits if abs(h - cited) <= WINDOW]
                    if len(near) == 1:
                        hits = near
                if len(hits) == 1:
                    if hits[0] == cited:
                        # Already pointing at the right line. Rewriting it to
                        # the identical string and counting that as a fix is how
                        # a tool comes to report hundreds of changes while
                        # changing nothing.
                        fine += 1
                        continue
                    new_line = new_line[:m.start()] + f"`{path}:{hits[0]}`" + new_line[m.end():]
                    moved += 1
                    touched += 1
                elif len(hits) > 1:
                    ambiguous += 1
                else:
                    absent += 1
            out[i] = new_line

        if touched and apply:
            md.write_text("\n".join(out) + "\n")
        if touched:
            print(f"  {md.relative_to(CORPUS)}: {touched} citation(s) relocated")

    print(f"\n{'relocated' if apply else 'would relocate'} {moved}; "
          f"{fine} already correct; {ambiguous} left alone (anchor appears more than once); "
          f"{absent} left alone (anchor not in the file at all, needs a human or an agent)")
    if not apply:
        print("dry run. pass --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
