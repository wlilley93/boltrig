#!/usr/bin/env python3
"""Gate: every citation in the Boltrig brownfield corpus must resolve.

Three things this gate asserts, in order:

  1. THE REFERENT IS THE PINNED ONE. The tree this runs in must be at the
     commit the corpus was written against. A verifier that cannot pin its
     referent verifies nothing: it will happily confirm citations against a
     tree that has moved under it. This check runs first and hard-fails.

  2. EVERY CITATION RESOLVES. path:line must exist and be in range.

  3. EVERY CITATION IS ANCHORED, AND THE ANCHOR IS STILL THERE. A bare
     path:line rots silently: the file changes, the line number still parses,
     and the citation now points at something else while still looking valid.
     Each citation carries a verbatim anchor, which must be found within
     +/- WINDOW lines of the cited line. Found-but-drifted is reported.

Exit 1 on any failure. `--selftest` proves the gate can fail, by running it
against deliberately broken citations; a gate that has never been shown to
fail is not evidence of anything.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PIN = "19bcae7fa81663fe8998377c86451ba08fb16e48"
WINDOW = 4
CORPUS = Path(__file__).resolve().parent
ROOT = CORPUS.parent.parent

# `path/to/file.ext:123` inside backticks. Path chars deliberately narrow so
# prose like `a:b` does not match.
CITE = re.compile(r"`([A-Za-z0-9_./-]+\.[A-Za-z0-9_]{1,12}):(\d+)`")
# An anchor is the next backticked or double-quoted run after the citation. It
# may wrap onto the following line, so the search text is the remainder of the
# citation's line plus LOOKAHEAD following lines joined.
ANCHOR = re.compile(r'`"(.{3,300}?)"`' r"|`([^`\n]{3,300})`" r'|"([^"\n]{3,300})"')
LOOKAHEAD = 2
# The same shape as CITE but without the backticks, for testing whether an
# anchor candidate is really just the next citation.
BARE_CITE = re.compile(r"[A-Za-z0-9_./-]+\.[A-Za-z0-9_]{1,12}:\d+")


def unescape(anchor: str) -> str:
    """Markdown-escaped quotes never match raw source. `\\"x\\"` means `"x"`."""
    return anchor.replace('\\"', '"').replace("\\\\", "\\")

SKIP_FILES = {"AUTHORING-CONTRACT.md", "verify-citations.py"}


@dataclass
class Failure:
    kind: str
    where: str
    detail: str


def head_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        return f"<unresolvable: {exc}>"
    return out.stdout.strip()


def corpus_files() -> list[Path]:
    return sorted(
        p for p in CORPUS.rglob("*.md")
        if p.name not in SKIP_FILES
    )


def check_citation(src: Path, lineno: int, path: str, target_line: int,
                   anchor: str | None) -> list[Failure]:
    where = f"{src.relative_to(CORPUS)}:{lineno}"
    target = ROOT / path
    if not target.exists():
        return [Failure("NO-SUCH-FILE", where, f"{path} does not exist in the pinned tree")]
    if target.is_dir():
        return [Failure("NOT-A-FILE", where, f"{path} is a directory")]
    try:
        lines = target.read_text(errors="replace").splitlines()
    except OSError as exc:
        return [Failure("UNREADABLE", where, f"{path}: {exc}")]
    if not (1 <= target_line <= len(lines)):
        return [Failure("LINE-OUT-OF-RANGE", where,
                        f"{path}:{target_line} but the file has {len(lines)} lines")]
    if anchor is None:
        return [Failure("UNANCHORED", where,
                        f"{path}:{target_line} carries no verbatim anchor")]

    needle = " ".join(unescape(anchor).split())
    lo = max(0, target_line - 1 - WINDOW)
    hi = min(len(lines), target_line + WINDOW)
    window = [" ".join(lines[i].split()) for i in range(lo, hi)]
    for offset, hay in enumerate(window):
        if needle in hay:
            actual = lo + offset + 1
            if actual != target_line:
                return [Failure("DRIFTED", where,
                                f"{path}: anchor found at line {actual}, cited as {target_line}")]
            return []
    return [Failure("ANCHOR-NOT-FOUND", where,
                    f"{path}:{target_line} anchor {needle!r} not within +/-{WINDOW} lines")]


def scan(files: list[Path]) -> tuple[int, list[Failure]]:
    total = 0
    failures: list[Failure] = []
    for src in files:
        lines = src.read_text(errors="replace").splitlines()
        fenced = False
        for lineno, line in enumerate(lines, 1):
            # A citation inside a fenced block is an EXAMPLE of the citation
            # form, not a claim about the tree. Checking it produces a confident
            # failure against a path nobody ever asserted existed.
            if line.lstrip().startswith("```"):
                fenced = not fenced
                continue
            if fenced:
                continue
            for m in CITE.finditer(line):
                total += 1
                tail = " ".join([line[m.end():], *lines[lineno:lineno + LOOKAHEAD]])
                anchor = None
                for am in ANCHOR.finditer(tail):
                    cand = next(g for g in am.groups() if g is not None)
                    # The next backticked run after a citation is sometimes the
                    # NEXT citation, in an enumeration like "[a:1], [b:2], [c:3]".
                    # Treating that as this citation's anchor produces a
                    # confidently wrong ANCHOR-NOT-FOUND instead of the honest
                    # answer, which is that the citation has no anchor.
                    if BARE_CITE.fullmatch(cand.strip()):
                        break
                    anchor = cand
                    break
                failures.extend(
                    check_citation(src, lineno, m.group(1), int(m.group(2)), anchor)
                )
    return total, failures


def selftest() -> int:
    """Prove the gate can fail. Each seed must be caught by its named kind."""
    import tempfile

    seeds = [
        ("NO-SUCH-FILE", "`boltrig/definitely_not_here.py:1` `\"anything\"`"),
        ("LINE-OUT-OF-RANGE", "`pyproject.toml:999999` `\"anything\"`"),
        ("UNANCHORED", "`pyproject.toml:1` and then nothing quoted at all."),
        ("ANCHOR-NOT-FOUND", "`pyproject.toml:1` `\"zzz not in this file zzz\"`"),
    ]
    # Shapes that must NOT be flagged: an anchor wrapped onto the next line, and
    # an anchor whose quotes are markdown-escaped. Both were false positives in
    # an earlier revision of this gate and both silently discredit real work.
    negatives = [
        ("wrapped anchor", '`scripts/check_architecture.py:57`\n`"_KERNEL_ROOT = (\\"boltrig\\", \\"kernel\\")"`'),
        ("escaped quotes", '`scripts/check_architecture.py:58` `"_KERNEL_FORBIDDEN = (\\"boltrig.fleet\\", \\"services\\")"`'),
    ]
    caught, missed = 0, []
    with tempfile.TemporaryDirectory(dir=CORPUS) as td:
        for kind, text in seeds:
            p = Path(td) / f"seed-{kind}.md"
            p.write_text(text + "\n")
            _, fails = scan([p])
            if any(f.kind == kind for f in fails):
                caught += 1
            else:
                missed.append((kind, [f.kind for f in fails]))
            p.unlink()
        false_pos = []
        for name, text in negatives:
            p = Path(td) / f"neg-{name.replace(' ', '-')}.md"
            p.write_text(text + "\n")
            _, fails = scan([p])
            if fails:
                false_pos.append((name, [f.kind for f in fails]))
            p.unlink()
    if missed:
        print(f"SELFTEST FAILED: {len(missed)} seeded violation(s) not caught")
        for kind, got in missed:
            print(f"  seeded {kind}, gate returned {got or '[]'}")
        return 1
    if false_pos:
        print(f"SELFTEST FAILED: {len(false_pos)} valid citation(s) wrongly flagged")
        for name, got in false_pos:
            print(f"  {name} flagged as {got}")
        return 1
    print(f"selftest OK: {caught}/{len(seeds)} seeded violations caught, "
          f"{len(negatives)}/{len(negatives)} valid shapes passed clean")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--allow-unpinned", action="store_true",
                    help="report the pin mismatch but keep going (for authoring, never for a filing)")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    head = head_commit()
    if head != PIN:
        print(f"REFERENT MISMATCH: corpus is pinned to {PIN[:12]}, tree HEAD is {head[:12]}")
        if not args.allow_unpinned:
            print("Every citation below would be verified against the wrong tree. Refusing.")
            return 1
        print("--allow-unpinned given: continuing against a tree that is NOT the referent.")

    files = corpus_files()
    total, failures = scan(files)
    print(f"corpus: {len(files)} files, {total} citations, referent {head[:12]}")
    if not failures:
        print("all citations resolve and are anchored")
        return 0

    by_kind: dict[str, int] = {}
    for f in failures:
        by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
    for f in failures:
        print(f"  {f.kind:18} {f.where:56} {f.detail}")
    print(f"\n{len(failures)} failure(s): " + ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items())))
    return 1


if __name__ == "__main__":
    sys.exit(main())
