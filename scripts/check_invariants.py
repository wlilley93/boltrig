#!/usr/bin/env python3
"""The binding-invariant gate (K-29 / K-30 ratchet). Stdlib only.

A binding invariant is a guarantee Nankle claims to enforce. The claim is only
worth anything if a test pins it. This script makes that mechanical:

  (a) scan tests/ for every ``@pytest.mark.invariant("X")`` marker and the test
      function that carries it (the markers are the ground truth);
  (b) load tests/invariants.yaml, the declared catalogue of invariants;
  (c) FAIL (exit 1) if any declared invariant has zero bound tests (an unbound
      claim is a build failure), or if any marker found in the tests is not
      declared in the catalogue (an undeclared invariant);
  (d) print a coverage table and the binding-debt count. Exit 0 only when every
      declared invariant is bound and every marker is declared (debt == 0).

Binding debt may only ever decrease: wire the gate into CI so a regression
(an unbound claim, or a stray marker) turns the build red.

Usage:  python scripts/check_invariants.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = ROOT / "tests"
CATALOGUE = TESTS_DIR / "invariants.yaml"

_MARKER_RE = re.compile(r"""@pytest\.mark\.invariant\(\s*["']([^"']+)["']\s*\)""")
_DEF_RE = re.compile(r"""^\s*(?:async\s+)?def\s+(test\w*)\s*\(""")


def _node_id(path: Path, test_name: str) -> str:
    """A pytest-style node id: forward-slash path relative to the repo root."""
    rel = path.relative_to(ROOT).as_posix()
    return f"{rel}::{test_name}"


def scan_markers() -> dict[str, set[str]]:
    """Map each invariant id to the set of test node ids that carry its marker."""
    found: dict[str, set[str]] = {}
    for path in sorted(TESTS_DIR.rglob("test_*.py")):
        pending: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            marker = _MARKER_RE.search(line)
            if marker:
                pending.append(marker.group(1))
                continue
            def_match = _DEF_RE.match(line)
            if def_match and pending:
                node = _node_id(path, def_match.group(1))
                for inv_id in pending:
                    found.setdefault(inv_id, set()).add(node)
                pending = []
    return found


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
        return value[1:-1]
    return value


def load_catalogue(path: Path) -> dict[str, dict]:
    """Parse the controlled invariants.yaml subset (no third-party yaml dep)."""
    data: dict[str, dict] = {}
    current: str | None = None
    in_tests = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            current, in_tests = None, False  # the top-level "invariants:" key
            continue
        if indent == 2 and stripped.endswith(":"):
            current = stripped[:-1].strip()
            data[current] = {"description": "", "tests": []}
            in_tests = False
            continue
        if indent == 4 and current is not None:
            if stripped.startswith("description:"):
                data[current]["description"] = _unquote(stripped[len("description:"):])
                in_tests = False
            elif stripped.startswith("tests:"):
                in_tests = True
            continue
        if indent >= 6 and stripped.startswith("- ") and in_tests and current is not None:
            data[current]["tests"].append(_unquote(stripped[2:]))
    return data


def main() -> int:
    if not CATALOGUE.exists():
        print(f"FAIL: missing catalogue {CATALOGUE.relative_to(ROOT)}", file=sys.stderr)
        return 1

    markers = scan_markers()
    catalogue = load_catalogue(CATALOGUE)

    declared = set(catalogue)
    marked = set(markers)

    unbound = sorted(i for i in declared if not markers.get(i))          # claim, no test
    undeclared = sorted(i for i in marked if i not in declared)          # test, no claim

    # Drift: a node id claimed in the catalogue that no marker actually backs.
    drift: list[str] = []
    for inv_id, meta in catalogue.items():
        real = markers.get(inv_id, set())
        for claimed in meta["tests"]:
            if claimed not in real:
                drift.append(f"{inv_id}: claims {claimed} but no such marker exists")

    # --- coverage table -----------------------------------------------------
    print("Invariant coverage")
    print("-" * 64)
    print(f"{'invariant':<14}{'declared':>10}{'bound':>8}  status")
    print("-" * 64)
    for inv_id in sorted(declared):
        claimed_n = len(catalogue[inv_id]["tests"])
        bound_n = len(markers.get(inv_id, set()))
        status = "ok" if bound_n else "UNBOUND"
        print(f"{inv_id:<14}{claimed_n:>10}{bound_n:>8}  {status}")
    print("-" * 64)

    debt = len(unbound) + len(undeclared)
    total_tests = sum(len(v) for v in markers.values())
    print(
        f"declared={len(declared)}  marked={len(marked)}  "
        f"bound_tests={total_tests}  binding_debt={debt}"
    )

    if unbound:
        print("\nUNBOUND invariants (declared but no test binds them):")
        for inv_id in unbound:
            print(f"  - {inv_id}")
    if undeclared:
        print("\nUNDECLARED invariants (a marker in tests/ not in invariants.yaml):")
        for inv_id in undeclared:
            for node in sorted(markers[inv_id]):
                print(f"  - {inv_id}  ({node})")
    if drift:
        print("\nCATALOGUE DRIFT (claimed node ids with no backing marker):")
        for line in drift:
            print(f"  - {line}")

    if debt or drift:
        print("\nRESULT: FAIL - binding debt must be zero (and may only decrease).")
        return 1
    print("\nRESULT: PASS - every declared invariant is bound and every marker is declared.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
