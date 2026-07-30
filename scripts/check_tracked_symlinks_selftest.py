#!/usr/bin/env python3
"""Seeded-failure tests for check_tracked_symlinks.py.

On this repository the gate has nothing to find the moment the .venv link is
removed, and a check whose only observed state is green is not yet known to be a
check at all. So every case it claims to refuse gets a case here, and so does
every case it must NOT refuse - a gate that fails an honest relative link would
be switched off within a week.

Two of the cases are about .gitignore rather than the gate, and they are the
point: they prove the hazard is real by reproducing it. `.venv/` does not stop a
SYMLINK named .venv from being added, and `.venv` does. That asymmetry is the
whole reason the defect reached main, and if a future edit "tidies" the ignore
rule back to the slash form these two go red together.

Hermetic: a throwaway git repository per case, so nothing depends on this
repository's own state.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
GATE = HERE / "check_tracked_symlinks.py"

passed = 0
failed = 0

_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    "PATH": "/usr/bin:/bin",
}


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(args), cwd=cwd, capture_output=True, text=True,
        env={**_ENV, "HOME": str(cwd)},
    )


def build() -> Path:
    root = Path(tempfile.mkdtemp())
    _run(root, "git", "init", "-q", "-b", "main")
    (root / "real.txt").write_text("x", encoding="utf-8")
    return root


def commit(root: Path) -> None:
    _run(root, "git", "add", "-A")
    _run(root, "git", "commit", "-q", "-m", "seed")


def check(name: str, root: Path, want_exit: int, *must_appear: str) -> None:
    global passed, failed
    proc = subprocess.run(
        [sys.executable, str(GATE), "--root", str(root)],
        cwd=root, capture_output=True, text=True, env={**_ENV, "HOME": str(root)},
    )
    out = proc.stdout + proc.stderr
    if proc.returncode != want_exit:
        print(f"FAIL {name:<56} exit={proc.returncode} want={want_exit}")
        print("\n".join(f"       {line}" for line in out.splitlines()))
        failed += 1
        return
    # The exit code alone would let the gate be right for the wrong reason, so
    # each case also names the sentence the operator has to be told.
    for want in must_appear:
        if want not in out:
            print(f"FAIL {name:<56} exit={proc.returncode} but output lacks: {want}")
            print("\n".join(f"       {line}" for line in out.splitlines()))
            failed += 1
            return
    print(f"ok   {name:<56} exit={proc.returncode}")
    passed += 1


# --- controls: what must NOT be refused ------------------------------------
r = build()
commit(r)
check("control: a repo with no symlinks at all", r, 0, "tracked symlinks=0", "RESULT: PASS")

r = build()
os.symlink("real.txt", r / "alias.txt")
commit(r)
check("control: a RELATIVE link to a file inside the tree", r, 0, "RESULT: PASS")

r = build()
(r / "sub").mkdir()
os.symlink("../real.txt", r / "sub" / "up.txt")
commit(r)
check("control: a relative link that climbs but stays inside", r, 0, "RESULT: PASS")

# --- THE case: a link pointing at itself -----------------------------------
r = build()
os.symlink(str(r / ".venv"), r / ".venv")
commit(r)
check(
    "THE .venv case: a symlink pointing at itself",
    r, 1,
    "does not resolve",
    "RESULT: FAIL",
)

# --- dangling ---------------------------------------------------------------
r = build()
os.symlink("nowhere.txt", r / "dangling.txt")
commit(r)
check("a dangling relative link", r, 1, "does not resolve")

r = build()
os.symlink("/no/such/path/at/all", r / "dangling-abs.txt")
commit(r)
check("a dangling absolute link", r, 1, "does not resolve")

# --- resolves, but not to anywhere this repository contains -----------------
r = build()
os.symlink("/etc/hostname", r / "host.txt")
commit(r)
check("an absolute link to a real file outside the repo", r, 1, "OUTSIDE the repository")

r = build()
outside = Path(tempfile.mkdtemp())
(outside / "elsewhere.txt").write_text("x", encoding="utf-8")
os.symlink(f"../{outside.name}/elsewhere.txt", r / "escape.txt")
# The link only resolves if the two temp dirs are siblings, which mkdtemp makes
# them; if that ever stops being true the case becomes the dangling one, which
# this gate also refuses, so it cannot silently start passing.
commit(r)
check("a relative link that climbs OUT of the repo", r, 1, "OUTSIDE the repository", "RESULT: FAIL")

# --- the .gitignore asymmetry that let this happen --------------------------
# Not a test of the gate. A test of the CAUSE, so nobody re-introduces it by
# "tidying" the ignore rule.
r = build()
(r / ".gitignore").write_text(".venv/\n", encoding="utf-8")
os.symlink(str(r / ".venv"), r / ".venv")
commit(r)
tracked = _run(r, "git", "ls-files", ".venv").stdout.strip()
if tracked == ".venv":
    print(f"ok   {'.venv/ (slash) does NOT ignore a symlink - the cause':<56} tracked")
    passed += 1
else:
    print(f"FAIL {'.venv/ (slash) does NOT ignore a symlink - the cause':<56} got {tracked!r}")
    failed += 1

r = build()
(r / ".gitignore").write_text(".venv\n", encoding="utf-8")
os.symlink(str(r / ".venv"), r / ".venv")
commit(r)
tracked = _run(r, "git", "ls-files", ".venv").stdout.strip()
if tracked == "":
    print(f"ok   {'.venv (no slash) DOES ignore it - the cure':<56} untracked")
    passed += 1
else:
    print(f"FAIL {'.venv (no slash) DOES ignore it - the cure':<56} got {tracked!r}")
    failed += 1

print()
print(f"seeded cases: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
