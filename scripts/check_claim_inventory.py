#!/usr/bin/env python3
"""The Tier 0 ratchet: the committed inventory is current, and the residue may only shrink.

`GOAL-claims-must-be-load-bearing.md` closes with the only success criterion it is willing to
state: "the measure of success is therefore not a date but a ratchet: the number of unbound
load-bearing claims may only decrease". Until 2026-07-27 nothing measured that number, and the
document meanwhile described an inventory that did not exist. This is both halves.

TWO THINGS ARE CHECKED, and the first is the one that keeps the second honest:

  1. `docs/claim-inventory.tsv` regenerates BYTE-IDENTICALLY from the sources. A committed
     census nobody re-derives is a snapshot, and a snapshot of a claim surface is exactly the
     artefact class this whole goal exists to distrust. Regenerating and comparing means the
     file cannot be edited into agreement.

  2. The LOAD-BEARING NO-SUBJECT count is at or below the pinned baseline. That is the residue:
     a claim that asserts a security control and names nothing a machine can resolve. It is
     where two of the eleven original defects lived, and it is the only number here that is
     supposed to move.

WHY THE COUNT AND NOT A LIST. A per-claim allowlist was the first design and it was wrong: 236
entries would need 236 reasons, nobody would write them, and the file would become a rubber
stamp that made the number look managed. A single integer that may only fall cannot be gamed
without visibly falling, and rewording a claim to dodge the phrase list RAISES the ORDINARY
count while lowering this one, which the summary prints side by side.

THE HONEST LIMIT. Binding a claim here means giving it a resolvable subject, not proving it
true. A docstring that says "the token is never logged" and then names the redactor has moved
from NO-SUBJECT to SUBJECT-REACHED, and all that establishes is that the redactor exists and
runs. That is a real step and it is not the whole journey; `tests/invariants.yaml` is where a
claim goes to be proven.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_claim_inventory import OUT, ROOT, build  # noqa: E402

BASELINE = ROOT / "docs" / "refactoring" / "claim-inventory-baseline.json"


def main() -> int:
    rows = build()
    header = ["weight", "classification", "source", "location", "subject", "claim"]
    body = "\n".join(
        ["\t".join(header)]
        + ["\t".join(r[h].replace("\t", " ") for h in header) for r in rows]
    ) + "\n"

    failures: list[str] = []

    # `relative_to` is deliberately not used: OUT is monkeypatched to a tmp path by the seeded
    # failure test, and a display helper that raises on a path outside the repo would make the
    # gate crash exactly where it is supposed to report. A gate that dies while reporting is a
    # gate that gets read as infrastructure noise.
    shown = OUT.name if ROOT not in OUT.parents else OUT.relative_to(ROOT).as_posix()
    if not OUT.exists():
        failures.append(f"{shown} does not exist. Run `make claim-inventory`.")
    elif OUT.read_text(encoding="utf-8") != body:
        failures.append(
            f"{shown} is STALE: it is not what the sources now say.\n"
            "  Regenerate with `make claim-inventory` and commit the result. A census nobody\n"
            "  re-derives is a snapshot, and this goal exists to distrust those."
        )

    residue = sum(
        1 for r in rows
        if r["weight"] == "LOAD-BEARING" and r["classification"] == "NO-SUBJECT"
    )
    ordinary = sum(
        1 for r in rows
        if r["weight"] == "ORDINARY" and r["classification"] == "NO-SUBJECT"
    )
    reached = sum(1 for r in rows if r["classification"] == "SUBJECT-REACHED")
    absent = [r for r in rows if r["classification"] == "SUBJECT-ABSENT"]

    baseline = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
    pinned = baseline.get("load_bearing_no_subject")

    print("Claim inventory")
    print(f"  claims                       {len(rows)}")
    print(f"  SUBJECT-REACHED              {reached}")
    print(f"  LOAD-BEARING, no subject     {residue}"
          + (f"   (baseline {pinned})" if pinned is not None else ""))
    print(f"  ORDINARY, no subject         {ordinary}")

    # A claim whose named subject nothing reaches. `unwired-claims` catches this for symbols it
    # can see; this catches it for a symbol named only in prose, which is the same defect
    # arriving by the other door.
    for r in absent:
        failures.append(
            f"SUBJECT-ABSENT at {r['location']}: the claim names `{r['subject']}`, which nothing "
            "outside its own definition mentions. Either the claim outlived its subject, or the "
            "subject was never wired."
        )

    if pinned is None:
        failures.append(
            "no baseline pinned. Write docs/refactoring/claim-inventory-baseline.json with\n"
            f'  {{"load_bearing_no_subject": {residue}, "pinned_at": "...", "note": "..."}}'
        )
    elif residue > pinned:
        failures.append(
            f"the residue GREW: {residue} load-bearing claims name nothing resolvable, and the\n"
            f"  baseline is {pinned}. This number may only decrease (the goal's own ratchet).\n"
            "  Either name the mechanism the new claim rests on, or do not make the claim."
        )

    if failures:
        print()
        for f in failures:
            print(f"  - {f}")
        print("\nRESULT: FAIL - the claim inventory is stale, or the residue grew.")
        return 1

    if pinned is not None and residue < pinned:
        print(f"\n  the residue FELL, {pinned} -> {residue}. Re-pin the baseline in this change.")
    print("\nRESULT: PASS - the inventory is current and the residue has not grown.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
