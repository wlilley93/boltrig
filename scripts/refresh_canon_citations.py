#!/usr/bin/env python3
"""Re-vendor the canon citator that check_prose_references.py resolves against.

Orders are federated: boltrig cites canon rulings it does not hold. The prose
gate's first cut resolved those by reading the canon repository straight off the
author's disk - so it passed here and reddened main the moment CI ran it, because
that directory exists on exactly one machine. That is the environment-dependent
gate class the goal it serves exists to close, built into the gate that closes it.

So the citator is a FILE in this repository, and this script is the deliberate
act of refreshing it. Run it when a new canon ruling starts being cited here; a
citation absent from the vendored file fails the gate, which is the point.

Usage:  python scripts/refresh_canon_citations.py [--canon PATH]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".vjs" / "canon-citations.txt"

HEADER = """\
# Citations the CANON register answers to, vendored into this subscriber repo.
#
# Orders are federated: boltrig cites canon rulings it does not hold. The prose
# gate used to resolve those by READING ~/Projects/vibe-justice-system/.vjs on the
# author's machine, which is why it passed here and failed the moment CI ran it -
# a check passing because of a directory on one box, which is the exact defect
# class the goal it serves exists to close, built into the gate that closes it.
#
# So the citator is vendored. Refresh it deliberately with
# `make refresh-canon-citations` when a new canon ruling is cited here; a
# citation absent from this file fails the gate, which is the point.
"""


def citations_in(*registers: Path) -> set[str]:
    """Every citation the canon repository answers to, across BOTH of its estates.

    Two roots, not one, and the second was missing until 2026-07-27. Canon keeps filed orders
    under `.vjs/orders/` and ENACTED law under `lawpack/v2/orders/`, and this script read only
    the first. The effect was quiet in the worst way: `[2026] VJS-PC 20` is in `.vjs` and
    vendored fine, so the citator looked complete, while `[2026] VJS-PC 19` is in the lawpack
    alone and any record citing it failed the prose gate as though the ruling did not exist.
    A subscriber could not cite most of the enacted constitution and nothing said so.
    """
    found: set[str] = set()
    for register in registers:
        found |= _citations_under(register)
    return found


def _citations_under(register: Path) -> set[str]:
    found: set[str] = set()
    for path in sorted(register.rglob("*.yaml")):
        if "orders" not in path.parts:
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            key, _, value = line.partition(":")
            if key.strip() not in {"id", "citation"}:
                continue
            value = value.strip().strip("'\"")
            if not value:
                continue
            found.add(value)
            # An `id:` of the form YEAR-VJS-... is cited in prose with the year
            # bracketed instead of hyphenated, so record that form too.
            head, _, rest = value.partition("-")
            if head.isdigit() and rest:
                found.add(f"[{head}] {rest}")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--canon", type=Path, default=Path.home() / "Projects" / "vibe-justice-system",
        help="path to the canon VJS repository",
    )
    args = parser.parse_args()
    registers = [args.canon / ".vjs", args.canon / "lawpack"]
    missing = [r for r in registers if not r.is_dir()]
    if missing:
        print(
            "FAIL: no canon register at " + ", ".join(str(r) for r in missing)
            + ". This script is the only thing allowed to read canon; the gate reads the "
            "vendored file. BOTH estates are required: filed orders live under .vjs/orders "
            "and enacted law under lawpack/v2/orders, and reading only the first silently "
            "made most of the constitution uncitable here.",
            file=sys.stderr,
        )
        return 1
    found = citations_in(*registers)
    if not found:
        roots = ", ".join(str(r) for r in registers)
        print(f"FAIL: {roots} yielded no citations; refusing to blank the citator.",
              file=sys.stderr)
        return 1
    OUT.write_text(HEADER + "\n".join(sorted(found)) + "\n", encoding="utf-8")
    print(f"vendored {len(found)} canon citations -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
