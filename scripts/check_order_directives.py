#!/usr/bin/env python3
"""The order-binding gate: a court directive must be enforced by something.

GOAL-claims-must-be-load-bearing, Tier 2, and specifically the bar that goal
sets for item 2: "every ORDER directive that says 'must' is bound to something
mechanical, the way D8 now is."

WHY. An order is the strongest claim this repository makes about itself: a court
found a defect, ordered a remedy, and the order sits in .vjs/orders/ marked
`status: binding`. Nothing checked that any of it was carried out. D8 of the
lease-fence ruling - "nothing on the refused path may consume or delete the
evidence" - was enforced only by a test whose docstring happened to mention it;
delete that test and the directive becomes enforceable by nothing, silently,
while the order still reads `binding`. That already happened once in a
neighbouring form: an order pointed at a renamed test (the SEC-24 drift) and sat
red for ninety minutes because a rename could not break anything.

WHAT COUNTS AS BOUND. A test that names the DIRECTIVE id as a word within
PROXIMITY_LINES of a line naming the ORDER (by id, by citation, or by the
distinctive tail of its id). The proximity matters and was learned the hard way:
the first version accepted the two anywhere in the same FILE, and the gate's own
new test file - which names six orders and, between them, directives D1, D5, D6
and D8 - immediately cross-matched, reporting a rate-limit directive bound by a
line about cancellation. Re-measured, whole-file matching had been counting 57
directives bound where same-line-or-adjacent counts 36. The gate that measures
debt is the last place an over-count is tolerable, so it reports the smaller,
true number.

That pairing is deliberately strict in one direction and loose in the other:

  - strict: the mention must be in tests/, not in boltrig/. A comment in
    production code saying "D4 requires this" is the claim, not the enforcement.
    Being able to write the comment is precisely the failure mode.
  - loose: it does not try to judge whether the test actually PROVES the
    directive. It cannot, and pretending otherwise would be this gate committing
    the defect it exists to catch. What it enforces is that a named, locatable
    test claims the directive - so renaming or deleting that test turns the
    binding red, which is the drift half of the problem and the half a machine
    can decide.

WHAT IT DOES NOT CHECK. Whether the bound test is any good, whether it would fail
if the directive were violated, and whether an order marked `binding` was rightly
decided. The first is what the invariant catalogue and the seeded-failure
discipline are for; the last is the court's, not a script's.

UNBOUND DIRECTIVES must carry an entry in
docs/refactoring/order-binding-exemptions.json giving an owner, a REASON a reader
can check, and an expiry - the shape of structural-exemptions.json. An exemption
that has expired, that names a directive with no finding, or that gives no reason
is itself a failure, because a stale waiver over a court order is the worst
version of the thing this whole programme is removing.

Usage:  python scripts/check_order_directives.py
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scan_guard import require_scanned  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ORDERS = ROOT / ".vjs" / "orders"
TESTS = ROOT / "tests"
EXEMPTIONS = ROOT / "docs" / "refactoring" / "order-binding-exemptions.json"

# How far a directive id may sit from the line naming its order. Zero would be
# defensible and is nearly right - almost every real binding writes them together,
# `# --- SEC-97 / COUNTY 7 D1: ...` - but a wrapped comment or a docstring that
# puts the citation on one line and the directives on the next is normal English,
# not evasion. Two lines admits that and nothing else: it changes the count by
# exactly the seven bindings that wrap, and re-admits no cross-match.
PROXIMITY_LINES = 2

# Read with an indentation scanner rather than a YAML parser, for the same reason
# check_invariants.py and check_health_claims.py do: these gates ship stdlib-only
# so they run in any environment, including one where the dev extras are absent.
# Only four keys are needed, and tests/unit/test_claim_gates.py holds this reader
# to a real YAML parser's answer so the shortcut cannot quietly diverge.
_ID = re.compile(r"^id:\s*(\S+)")
_STATUS = re.compile(r"^status:\s*(\S+)")
_CITATION = re.compile(r"^citation:\s*(.+?)\s*$")
_DIRECTIVE_ID = re.compile(r"^-\s+id:\s*(\S+)")


def parse_order(path: Path) -> dict:
    """Extract {id, status, citation, directives} from one order file."""
    order = {"id": "", "status": "", "citation": "", "directives": []}
    in_directives = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if line.startswith("directives:"):
            in_directives = True
            continue
        if in_directives:
            # A new top-level key ends the directive list.
            if line[:1] not in {" ", "-"}:
                in_directives = False
            else:
                match = _DIRECTIVE_ID.match(line.strip())
                if match:
                    order["directives"].append(match.group(1).strip("\"'"))
                continue
        for key, pattern in (("id", _ID), ("status", _STATUS), ("citation", _CITATION)):
            if not order[key]:
                match = pattern.match(line)
                if match:
                    value = match.group(1).strip().strip("\"'")
                    # YAML's null spellings are ABSENCE, not the four-character string
                    # "null". This reader is a shortcut over a real parser and the test
                    # beside it exists to keep the two agreeing; the first order to write
                    # `citation: null` rather than omitting the key is what found the gap.
                    # An order whose citation was deliberately withheld would otherwise have
                    # been keyed by the literal "null", so any test naming another such order
                    # would have cross-matched it.
                    order[key] = "" if value in {"null", "~", "Null", "NULL"} else value
    return order


def order_keys(order: dict) -> set[str]:
    """Every string a test might reasonably use to name this order.

    The full id, the citation, and the id's distinctive tail - tests cite
    `WORK-ITEM-LEASE-FENCE-001` far more often than the full
    `2026-VJS-CC-BOLTRIG-WORK-ITEM-LEASE-FENCE-001`, and refusing the short form
    would push authors towards satisfying the gate rather than reading well.
    """
    keys = {order["id"], order["citation"]}
    tail = re.match(r"\d{4}-VJS-[A-Z]+-BOLTRIG-(.+)", order["id"])
    if tail:
        keys.add(tail.group(1))
    return {key for key in keys if key}


def test_sources() -> dict[Path, str]:
    """Every test file that could bind a directive, in either language.

    The UI half is not optional: UI-TEST-HARNESS-001's directives are about the
    console's own test harness and CANNOT be bound by a pytest file. Scanning
    only tests/*.py would have reported five directives unbound and pushed the
    honest answer towards a waiver, when the enforcement lives in ui/ and in the
    Playwright config that names the order.
    """
    out: dict[Path, str] = {}
    roots = [
        (TESTS, ("*.py",)),
        (ROOT / "ui", ("*.test.ts", "*.test.tsx", "*.spec.ts", "*.spec.tsx",
                       "playwright.config.ts", "vitest.config.ts")),
    ]
    for base, patterns in roots:
        if not base.is_dir():
            continue
        for pattern in patterns:
            for path in sorted(base.rglob(pattern)):
                if any(
                    part.startswith(".") or part in {"__pycache__", "node_modules", "dist"}
                    for part in path.parts
                ):
                    continue
                try:
                    out[path] = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
    return out


def load_exemptions() -> tuple[dict[str, dict], list[str]]:
    """Read the waiver file, refusing a waiver that says nothing."""
    if not EXEMPTIONS.is_file():
        return {}, []
    try:
        raw = json.loads(EXEMPTIONS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"{EXEMPTIONS.name} does not parse: {exc}"]
    problems: list[str] = []
    valid: dict[str, dict] = {}
    today = date.today()
    for key, entry in (raw.get("allow") or {}).items():
        if not isinstance(entry, dict):
            problems.append(f"{key}: exemption is not an object")
            continue
        owner = str(entry.get("owner") or "").strip()
        reason = str(entry.get("reason") or "").strip()
        expires = str(entry.get("expires") or "").strip()
        if not owner or not reason or not expires:
            problems.append(f"{key}: an exemption needs owner, reason and expires")
            continue
        try:
            when = date.fromisoformat(expires)
        except ValueError:
            problems.append(f"{key}: expires '{expires}' is not an ISO date")
            continue
        if when < today:
            problems.append(f"{key}: exemption expired on {expires}")
            continue
        valid[key] = entry
    return valid, problems


def main() -> int:
    paths = sorted(ORDERS.glob("*.yaml")) if ORDERS.is_dir() else []
    require_scanned(paths, f"order files under {ORDERS.relative_to(ROOT).as_posix()}")
    sources = test_sources()
    require_scanned(sources, "test sources")

    exempt, problems = load_exemptions()
    bound: list[tuple[str, str, str]] = []
    unbound: list[tuple[str, str]] = []
    waived: set[str] = set()
    orders_checked = 0

    for path in paths:
        order = parse_order(path)
        if order["status"] != "binding":
            continue
        orders_checked += 1
        keys = order_keys(order)
        # Line numbers, not just files: the directive has to sit NEXT TO its order.
        naming: dict[Path, list[int]] = {}
        for p, text in sources.items():
            at = [
                i
                for i, line in enumerate(text.splitlines())
                if any(k in line for k in keys)
            ]
            if at:
                naming[p] = at
        short = order["id"].split("BOLTRIG-")[-1]
        for directive in order["directives"]:
            word = re.compile(rf"(?<![\w-]){re.escape(directive)}(?![\w-])")
            hits = [
                p
                for p, at in naming.items()
                if any(
                    word.search(line) and any(abs(i - j) <= PROXIMITY_LINES for j in at)
                    for i, line in enumerate(sources[p].splitlines())
                )
            ]
            key = f"{short}:{directive}"
            if hits:
                bound.append((short, directive, hits[0].relative_to(ROOT).as_posix()))
            elif key in exempt:
                waived.add(key)
            else:
                unbound.append((short, directive))

    stale = sorted(set(exempt) - waived)
    for key in stale:
        problems.append(f"{key}: exemption names a directive that is bound or absent")

    print("Court directives vs the tests that claim them")
    print("-" * 88)
    for short, directive, where in bound:
        print(f"  BOUND   {short:38} {directive:5} {where}")
    for key in sorted(waived):
        print(f"  waived  {key}")
    for short, directive in unbound:
        print(f"  UNBOUND {short:38} {directive}")
    print("-" * 88)
    print(
        f"orders={orders_checked}  directives={len(bound) + len(waived) + len(unbound)}  "
        f"bound={len(bound)}  waived={len(waived)}  unbound={len(unbound)}"
    )

    if unbound or problems:
        print()
        if unbound:
            print("UNBOUND court directives (enforceable by nothing):")
            for short, directive in unbound:
                print(f"  - [{short}] {directive}")
            print()
            print(
                "  Bind it: name the order AND the directive id in the test that "
                "enforces it.\n"
                f"  Or record it in {EXEMPTIONS.relative_to(ROOT).as_posix()} with an "
                "owner, a reason and an expiry."
            )
        for problem in problems:
            print(f"  ! {problem}")
        print()
        print("RESULT: FAIL - a binding directive is enforced by nothing.")
        return 1

    print()
    print("RESULT: PASS - every binding directive is bound to a test or recorded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
