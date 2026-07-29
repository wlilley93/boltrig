#!/usr/bin/env python3
"""Seeded-failure tests for check_commit_trailers.py.

The gate it tests will, on this repository, almost always pass: the corpus is 4
commits with a trailer and 1 known offender. A check like that becomes a
formality unless it is shown going red on purpose, and the class it guards is
already at its third instance - so every case it claims to catch gets a case here.

Hermetic: builds a throwaway git repository per case and points the gate at it,
so no case can depend on this repository's own history.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
GATE = HERE / "check_commit_trailers.py"

passed = 0
failed = 0


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(args), cwd=cwd, capture_output=True, text=True,
        env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
             "PATH": "/usr/bin:/bin", "HOME": str(cwd)},
    )


def build(commits: list[tuple[dict[str, str], str]]) -> Path:
    """A throwaway repo. Each commit is ({path: content}, message)."""
    root = Path(tempfile.mkdtemp())
    _run(root, "git", "init", "-q", "-b", "main")
    for files, message in commits:
        for name, content in files.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        _run(root, "git", "add", "-A")
        _run(root, "git", "commit", "-q", "--allow-empty", "-m", message)
    return root


def check(name: str, root: Path, want_exit: int, *must_appear: str) -> None:
    global passed, failed
    proc = subprocess.run(
        [sys.executable, str(GATE), "--ref", "main"],
        cwd=root, capture_output=True, text=True,
    )
    out = proc.stdout + proc.stderr
    if proc.returncode != want_exit:
        print(f"FAIL {name:<52} exit={proc.returncode} want={want_exit}")
        print("\n".join(f"       {line}" for line in out.splitlines()))
        failed += 1
        return
    # The exit code alone would let the gate be right for the wrong reason, so
    # each case also names the sentence the operator has to be told.
    for want in must_appear:
        if want not in out:
            print(f"FAIL {name:<52} exit={proc.returncode} but output lacks: {want}")
            print("\n".join(f"       {line}" for line in out.splitlines()))
            failed += 1
            return
    print(f"ok   {name:<52} exit={proc.returncode}")
    passed += 1


# --- the control: a trailer citing a file that is really there. Must PASS. ----
check(
    "control: cited path exists in that commit",
    build([({"docs/real.md": "x"}, "add it\n\nRefs: docs/real.md")]),
    0,
    "RESULT: PASS",
)

# --- THE defect: a trailer citing something that was never committed ---------
check(
    "cites a path that never existed",
    build([({"docs/real.md": "x"}, "add it\n\nRefs: docs/ghost.md")]),
    1,
    "did not exist in that commit's own tree",
    "RESULT: FAIL",
)

# --- judged against its OWN tree, not HEAD's --------------------------------
# A commit may legitimately cite a file later deleted. Judging history by today's
# tree would turn every honest deletion into a violation, so this case exists to
# stop anyone "simplifying" the gate into exactly that bug.
deleted = build([
    ({"docs/gone.md": "x"}, "add it\n\nRefs: docs/gone.md"),
])
_run(deleted, "git", "rm", "-q", "docs/gone.md")
_run(deleted, "git", "commit", "-q", "-m", "remove it")
check("a cited path deleted LATER is still fine", deleted, 0, "RESULT: PASS")

# --- and the converse: cited BEFORE it was added is not fine ----------------
check(
    "cited one commit before it was added",
    build([
        ({}, "cite it early\n\nRefs: docs/later.md"),
        ({"docs/later.md": "x"}, "actually add it"),
    ]),
    1,
    "did not exist in that commit's own tree",
)

# --- trailer spellings ------------------------------------------------------
for spelling in ("Refs", "Ref", "See", "refs", "SEE"):
    check(
        f"the {spelling}: spelling is read",
        build([({}, f"x\n\n{spelling}: docs/ghost.md")]),
        1,
        "did not exist",
    )

# --- an INDENTED trailer is a quotation, not a citation ---------------------
# This case exists because the gate flagged its OWN introducing commit: that
# message quotes 881a9df's `Refs:` line, indented, in order to explain what the
# gate is for. Git's own convention (git interpret-trailers) puts trailers flush
# left in the last paragraph, so indentation is exactly the signal that separates
# "I am citing this" from "I am talking about someone citing this".
check(
    "an indented Refs: naming a ghost is IGNORED",
    build([({"docs/real.md": "x"},
            "explain the defect\n\n    Refs: docs/ghost.md\n\nthat trailer dangles.\n\nRefs: docs/real.md")]),
    0,  # the real trailer resolves; the quoted ghost is prose and must not count
    "RESULT: PASS",
)
check(
    "an indented Refs: is not a trailer at all",
    build([({"a.md": "x"}, "explain it\n\n    Refs: docs/ghost.md")]),
    1,  # nothing here is a real trailer, so the empty-scan refusal is correct
    "found NO Refs:/See: trailer at all",
)
check(
    "a real trailer alongside a quoted one is still read",
    build([({"docs/real.md": "x"},
            "explain it\n\n    Refs: docs/ghost.md\n\nRefs: docs/real.md")]),
    0,
    "RESULT: PASS",
)

# --- what must NOT be treated as a path ------------------------------------
# The gate has no business guessing at non-paths. A false positive here would
# make it noisy enough to be switched off, which is how a gate dies.
for token in (
    "PERMIT-1785318255",
    "2026-VJS-CC-BOLTRIG-DEVELOPMENT-POSTURE-001",
    "#173",
    "SEC-179",
    "e.g.",
    "docs",
):
    check(
        f"not a path: {token}",
        build([({}, f"x\n\nRefs: {token}")]),
        0,
        "RESULT: PASS",
    )

# --- a body mentioning a missing file OUTSIDE a trailer is not a citation ---
check(
    "a missing path in prose, not on a trailer line",
    build([({}, "x\n\nI thought about docs/ghost.md and decided against it.")]),
    1,  # no trailer anywhere => the gate REFUSES rather than passing vacuously
    "found NO Refs:/See: trailer at all",
)

# --- the gate must not pass by finding nothing ------------------------------
check(
    "no trailer anywhere REFUSES (not a silent pass)",
    build([({"a.md": "x"}, "no trailer here")]),
    1,
    "broken scan",
)

# --- outside a repository it must SAY so, not traceback ---------------------
import shutil as _shutil

_export = Path(tempfile.mkdtemp())
(_export / "scripts").mkdir()
_shutil.copy(GATE, _export / "scripts" / GATE.name)
_proc = subprocess.run(
    [sys.executable, str(_export / "scripts" / GATE.name)],
    cwd=_export, capture_output=True, text=True,
)
_out = _proc.stdout + _proc.stderr
if _proc.returncode != 0 and "needs a real repository" in _out and "Traceback" not in _out:
    print(f"ok   {'outside a repo it says so, no traceback':<52} exit={_proc.returncode}")
    passed += 1
else:
    print(f"FAIL {'outside a repo it says so, no traceback':<52} exit={_proc.returncode}")
    print("\n".join(f"       {line}" for line in _out.splitlines()[:6]))
    failed += 1

print()
print(f"seeded cases: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
