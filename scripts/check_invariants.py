#!/usr/bin/env python3
"""The binding-invariant gate (K-29 / K-30 ratchet). Stdlib only.

A binding invariant is a guarantee Boltrig claims to enforce. The claim is only
worth anything if a test pins it. This script makes that mechanical:

  (a) scan tests/ for every ``@pytest.mark.invariant("X")`` marker and the test
      function that carries it (the markers are the ground truth);
  (b) load tests/invariants.yaml, the declared catalogue of invariants;
  (c) FAIL (exit 1) if any declared invariant has zero bound tests (an unbound
      claim is a build failure), or if any marker found in the tests is not
      declared in the catalogue (an undeclared invariant);
  (d) print a coverage table and the binding-debt count. Exit 0 only when every
      declared invariant is bound and every marker is declared (debt == 0).
      Bindings that only execute behind a live service are declared as
      ``service_gated`` in the catalogue and reported as gated-not-verified, so
      a permanently skipped test never silently "discharges" an invariant.

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


class CatalogueError(Exception):
    """The catalogue is malformed in a way that would silently lose a claim."""


def _unquote(value: str) -> str:
    """Undo the YAML scalar quoting used by the catalogue.

    A YAML single-quoted scalar escapes a literal apostrophe by DOUBLING it, so
    unquoting has to undo that or 84 of the 326 descriptions read back wrong.
    Descriptions are single-quoted (they carry colons and hashes, which a plain
    scalar cannot); node ids stay plain."""
    value = value.strip()
    if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
        inner = value[1:-1]
        return inner.replace("''", "'") if value[0] == "'" else inner
    return value


def load_catalogue(path: Path) -> dict[str, dict]:
    """Parse the controlled invariants.yaml subset (no third-party yaml dep).

    Besides ``description``/``tests`` an entry may declare ``service_gated``: a
    subset of its tests that only execute behind a service gate (a live Hatchet
    engine, cognee + LLM env, ...). Those bindings are real, but offline they are
    gated-not-verified - the gate reports them rather than letting a permanently
    skipped test silently "discharge" the invariant.

    A REPEATED invariant id raises. This reader used to let the later block
    overwrite the earlier one, and PyYAML's own duplicate-key handling is the
    same silent last-wins; SEC-169 was minted twice (2026-07-17 for the RLS
    fence-drift guard, 2026-07-22 for credential-at-rest sealing) and the RLS
    declaration was evicted from the catalogue, from this gate's coverage table
    and from docs/invariants.md for four months without one check going red. A
    catalogue whose whole job is to make claims fail loudly must not eat one."""
    data: dict[str, dict] = {}
    current: str | None = None
    in_tests = False
    in_gated = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            current, in_tests, in_gated = None, False, False  # top-level "invariants:"
            continue
        if indent == 2 and stripped.endswith(":"):
            current = stripped[:-1].strip()
            if current in data:
                raise CatalogueError(
                    f"duplicate invariant id {current!r} in "
                    f"{path.name}: the second block would silently evict the first"
                )
            data[current] = {"description": "", "tests": [], "service_gated": []}
            in_tests = in_gated = False
            continue
        if indent == 4 and current is not None:
            if stripped.startswith("description:"):
                data[current]["description"] = _unquote(stripped[len("description:"):])
                in_tests = in_gated = False
            elif stripped.startswith("tests:"):
                in_tests, in_gated = True, False
            elif stripped.startswith("service_gated:"):
                in_tests, in_gated = False, True
            continue
        if indent >= 6 and stripped.startswith("- ") and current is not None:
            if in_tests:
                data[current]["tests"].append(_unquote(stripped[2:]))
            elif in_gated:
                data[current]["service_gated"].append(_unquote(stripped[2:]))
    return data


def main() -> int:
    if not CATALOGUE.exists():
        print(f"FAIL: missing catalogue {CATALOGUE.relative_to(ROOT)}", file=sys.stderr)
        return 1

    markers = scan_markers()
    try:
        catalogue = load_catalogue(CATALOGUE)
    except CatalogueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    declared = set(catalogue)
    marked = set(markers)

    unbound = sorted(i for i in declared if not markers.get(i))          # claim, no test
    undeclared = sorted(i for i in marked if i not in declared)          # test, no claim

    # Drift: a node id claimed in the catalogue that no marker actually backs, or
    # a service_gated id that is not one of the invariant's declared tests.
    drift: list[str] = []
    for inv_id, meta in catalogue.items():
        real = markers.get(inv_id, set())
        for claimed in meta["tests"]:
            if claimed not in real:
                drift.append(f"{inv_id}: claims {claimed} but no such marker exists")
        for gated in meta["service_gated"]:
            if gated not in meta["tests"]:
                drift.append(
                    f"{inv_id}: service_gated {gated} is not one of its declared tests"
                )

    # --- coverage table -----------------------------------------------------
    print("Invariant coverage")
    print("-" * 64)
    print(f"{'invariant':<14}{'declared':>10}{'bound':>8}  status")
    print("-" * 64)
    for inv_id in sorted(declared):
        meta = catalogue[inv_id]
        claimed_n = len(meta["tests"])
        bound_n = len(markers.get(inv_id, set()))
        gated_n = len(meta["service_gated"])
        if not bound_n:
            status = "UNBOUND"
        elif gated_n >= claimed_n:
            # every binding needs a live service: offline this invariant is
            # gated-not-verified, not verified.
            status = "GATED"
        elif gated_n:
            status = f"ok ({gated_n} gated)"
        else:
            status = "ok"
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

    gated = [
        (inv_id, node)
        for inv_id in sorted(declared)
        for node in catalogue[inv_id]["service_gated"]
    ]
    if gated:
        # A warning, not debt: the binding exists, but it only executes in the
        # service-gated suites - offline it verifies nothing.
        print("\nSERVICE-GATED bindings (gated-not-verified offline; run the live suites):")
        for inv_id, node in gated:
            print(f"  - {inv_id}  ({node})")

    if debt or drift:
        print("\nRESULT: FAIL - binding debt must be zero (and may only decrease).")
        return 1
    print("\nRESULT: PASS - every declared invariant is bound and every marker is declared.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
