#!/usr/bin/env python3
"""Reachability is TRANSITIVE. A reader with a caller is not wired if that caller has none.

[2026] VJS-CC-BOLTRIG-WORKFLOW-PROMOTION-TRIGGER-001 D2, and its corollary 2: a gate that
measures to the FIRST HOP is honest about the paths it walks and cosmetic about the ones it does
not.

THE DEFECT. `check_unwired_claims.py` asks "does this name appear anywhere outside its own
definition". `WorkflowLibrary.match` did: it is called by `select_or_generate_workflow`. That
function is called by nothing in production. So an entire retrieval path, a learning leg and a
promotion subsystem sat behind one hop of apparent wiring, and a court was told the reader "runs
on every workflow selection" because the first hop looked fine. Nothing could contradict it.

WHAT THIS DOES. Builds a call graph over `boltrig/` and reports every function unreachable from
every root. It is NAME-BASED, like the gate beside it: a function is taken to reach name `N` if
`N` appears as a load inside its body. That over-approximates (two methods with the same name
merge), and over-approximation is the safe direction here: it makes the reachable set LARGER, so
anything this reports is unreachable even under a generous reading.

THE ROOTS ARE THE WHOLE ARGUMENT. Most are derived structurally, because a hand-list rots:

  * a DECORATED function. The decorator is the wiring: a route handler, a Hatchet task and a
    `@property` are all called by something that never spells the name.
  * a method OVERRIDING a base defined outside `boltrig/`. Starlette calls `dispatch`.
  * module-level code, which runs on import.
  * a dunder, which the interpreter calls.
  * a name reached through `getattr`/`hasattr`/`setattr` with a literal string.

The rest live in `docs/refactoring/reachability-roots.json`, and that file is the honest weak
point: an over-broad root set silently re-admits exactly the defect this exists to catch. Every
entry needs a reason naming what calls it and how. See the order's limit L1: no mechanical check
can hold "the root set is honest", so it is recorded as a limit and not dressed as a directive.

WHAT IT DOES NOT ESTABLISH. That a reachable function is ever actually called at runtime: a
path guarded by a config flag nobody sets is reachable here. It establishes the other direction
completely, and that is the direction the defect lives in.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "boltrig"
ROOTS_FILE = ROOT / "docs" / "refactoring" / "reachability-roots.json"


def _sources() -> list[Path]:
    """Cached and non-ignored new package files.

    Ignored local scratch cannot change the answer, while a real new module is
    included before its first staging operation. The claim inventory uses the
    same boundary.
    """
    import subprocess

    out = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
            "boltrig/**/*.py",
        ],
        capture_output=True, check=True, text=True,
    ).stdout
    # `.exists()` because `git ls-files` lists a cached path, including one deleted
    # in the working tree and not yet staged. A half-finished deletion is not a source file, and
    # crashing on one makes the gate look broken at exactly the moment someone is using it.
    return sorted(p for p in (ROOT / n for n in out.split("\0") if n) if p.exists())


class _Graph:
    def __init__(self) -> None:
        self.defined: dict[str, Path] = {}      # name -> where
        self.edges: dict[str, set[str]] = {}    # name -> names its body loads
        self.roots: set[str] = set()
        self.reasons: dict[str, str] = {}       # root -> why it is a root

    def add(self, name: str, path: Path, body_names: set[str]) -> None:
        self.defined.setdefault(name, path)
        self.edges.setdefault(name, set()).update(body_names)

    def root(self, name: str, why: str) -> None:
        self.roots.add(name)
        self.reasons.setdefault(name, why)


def _loads(node: ast.AST) -> set[str]:
    """Every name the body of this node reads, plus attribute tails and getattr literals."""
    found: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            found.add(n.id)
        elif isinstance(n, ast.Attribute):
            found.add(n.attr)
        elif isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name) and f.id in {"getattr", "hasattr", "setattr"}:
                for a in n.args[1:2]:
                    if isinstance(a, ast.Constant) and isinstance(a.value, str):
                        found.add(a.value)
    return found


def _build() -> _Graph:
    g = _Graph()
    local_bases: set[str] = set()
    for path in _sources():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.ClassDef):
                local_bases.add(n.name)

    for path in _sources():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue

        # Module level runs on import, so anything it loads is reached.
        module_body = [s for s in tree.body if not isinstance(
            s, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)]
        for name in _loads(ast.Module(body=module_body, type_ignores=[])):
            g.root(name, f"loaded at module level in {path.relative_to(ROOT)}")

        def walk(scope: ast.AST, cls: ast.ClassDef | None) -> None:
            for n in ast.iter_child_nodes(scope):
                if isinstance(n, ast.ClassDef):
                    # A class body runs on import too (decorators, field defaults).
                    for name in _loads(ast.Module(
                        body=[s for s in n.body if not isinstance(
                            s, ast.FunctionDef | ast.AsyncFunctionDef)],
                        type_ignores=[],
                    )):
                        g.root(name, f"class body of {n.name}")
                    for d in n.decorator_list:
                        for name in _loads(d):
                            g.root(name, f"decorator on class {n.name}")
                    walk(n, n)
                    continue
                if not isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef):
                    walk(n, cls)
                    continue

                g.add(n.name, path, _loads(n))
                if n.decorator_list:
                    g.root(n.name, "decorated, so something calls it without naming it")
                    for d in n.decorator_list:
                        for name in _loads(d):
                            g.root(name, f"named by a decorator on {n.name}")
                if n.name.startswith("__") and n.name.endswith("__"):
                    g.root(n.name, "a dunder, called by the interpreter")
                if cls is not None:
                    foreign = [b for b in cls.bases
                               if not (isinstance(b, ast.Name) and b.id in local_bases)]
                    if foreign:
                        g.root(n.name, f"{cls.name} extends a base defined outside boltrig/")
                walk(n, cls)

        walk(tree, None)
    return g


def main() -> int:
    g = _build()

    declared = json.loads(ROOTS_FILE.read_text(encoding="utf-8")) if ROOTS_FILE.exists() else {}
    entries = declared.get("roots", {})
    problems = [f"{n}: root declares no reason" for n, r in sorted(entries.items())
                if not str(r).strip()]
    for name in entries:
        g.root(name, "declared")

    seen: set[str] = set()
    frontier = [r for r in g.roots]
    while frontier:
        name = frontier.pop()
        if name in seen:
            continue
        seen.add(name)
        frontier.extend(g.edges.get(name, ()))

    unreachable = sorted(n for n in g.defined if n not in seen)

    print("Transitive reachability over boltrig/")
    print(f"  functions defined   {len(g.defined)}")
    print(f"  roots               {len(g.roots)} ({len(entries)} declared, the rest derived)")
    print(f"  reachable           {len(seen & set(g.defined))}")
    print(f"  UNREACHABLE         {len(unreachable)}")

    baseline = declared.get("unreachable_baseline")
    if problems:
        print()
        for p in problems:
            print(f"  - {p}")
    if unreachable:
        print("\n  unreachable from every root:")
        for n in unreachable:
            print(f"    {n}  ({g.defined[n].relative_to(ROOT)})")

    if problems:
        print("\nRESULT: FAIL - a declared root gives no reason.")
        return 1
    if baseline is None:
        # Not `relative_to`: the seeded-failure test points ROOTS_FILE outside the repo, and a
        # display helper that raises there would crash the gate exactly where it is meant to
        # report. Same correction the claim inventory needed on the same day.
        shown = ROOTS_FILE.name if ROOT not in ROOTS_FILE.parents else \
            ROOTS_FILE.relative_to(ROOT).as_posix()
        print(f"\nRESULT: FAIL - no baseline pinned in {shown} (`unreachable_baseline`).")
        return 1
    if len(unreachable) > baseline:
        print(f"\nRESULT: FAIL - {len(unreachable)} unreachable, baseline {baseline}. "
              "This number may only decrease: wire it, delete it, or declare a root with a "
              "reason naming what calls it and how.")
        return 1
    if len(unreachable) < baseline:
        print(f"\n  the count FELL, {baseline} -> {len(unreachable)}. Re-pin it in this change.")
    print("\nRESULT: PASS - nothing newly unreachable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
