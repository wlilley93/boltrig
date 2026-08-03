#!/usr/bin/env python3
"""No gate reports a pass over a tree it never read.

THE CLASS A MUTATION SWEEP CANNOT FIND, which is why this is a separate command. A mutation sweep
asks whether a test notices its subject being broken. It is structurally blind to a defect the gate
and its test AGREE about - and "an empty run is a passing run" is exactly that shape. In opbox-prod
on 2026-07-26, 105 mutation agents found no instance; pointing each gate at an empty root found SIX
in one command, including a census reporting a clean bill of health over ZERO gates. Every one of
those sentences was true the way an empty room is quiet.

WHY THIS REPO NEEDS IT DESPITE ALREADY HAVING scan_guard. `scripts/scan_guard.py::require_scanned`
is the right idea and better placed than any sweep: it refuses inside the gate, at the moment of
scanning, with a message that says a green here is most misleading precisely when a checkout is
truncated. But measured 2026-08-03, it is used by FIVE of the eighteen `check_*.py` gates, and
NOTHING enforces adoption. The other thirteen do refuse an empty tree today - I ran ten of them -
but by accident of how each happens to be written, not because anything holds them to it.

SO THIS TESTS THE PROPERTY, NOT THE HELPER. A gate that refuses an empty tree passes here however
it refuses; a gate that starts passing over nothing fails here whether or not it imports
scan_guard. Mandating the import would be enforcing a spelling. The 5/18 number is a real finding
and is recorded in the cross-repo register, but the lock belongs on the behaviour.

THE THREE LAWFUL ANSWERS over an empty tree: refuse; a usage error (it wanted an argument); or a
pass that names what it actually read. An unqualified pass is none of them.

WHAT THIS DOES NOT REACH, declared rather than silently skipped, because an undeclared exemption is
how this class survives. A gate that reads a live database, a running container, or the network has
no empty-tree form - the fixture cannot take those away, so its refusal here would be earned by
something other than the empty tree and would be a weaker proof than it looks.

Exit 0 clean, 1 when a gate passes over nothing, 2 when it could not ask.

    python3 scripts/check_no_vacuous_greens.py
    python3 scripts/check_no_vacuous_greens.py --self-test
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(os.environ.get("BOLTRIG_ROOT", Path(__file__).resolve().parents[1]))

# Gates that cannot be aimed at a fixture, with the reason. Each is a claim someone can check.
NO_EMPTY_TREE_FORM = {
    "check_fleet_drift.py":
        "probes running containers over ssh; the fixture cannot take the fleet away, so a refusal "
        "here would be earned by the missing fleet rather than by the empty tree",
    "check_codex_pin_health.py":
        "reads the Codex install on THIS box (a binary outside the repo), so an empty repo tree "
        "does not make it blind",
    "check_user_authority.py":
        "reads live GitHub org state over the network",
}

# A word a reader would take as "fine". Deliberately the gate's own success vocabulary rather than
# the exit code alone: a gate can exit 0 having printed nothing useful.
PASS_WORDS = ("OK", "PASS", "GREEN", "clean")


def gates() -> list[Path]:
    return sorted(
        p for p in (ROOT / "scripts").glob("check_*.py")
        if "selftest" not in p.name and p.name != Path(__file__).name
    )


def empty_tree_verdict(script: Path, fixture_root: Path) -> tuple[int, str]:
    """Run `script` inside a tree with the layout and none of the source."""
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        # The FULL scripts/ dir, because these gates import sibling helpers (scan_guard, scanlib).
        # An import crash is not a finding about vacuity, it is a finding about my fixture - and
        # the first version of this got exactly that wrong and reported ModuleNotFoundError as
        # though the gate had refused on the merits.
        shutil.copytree(fixture_root / "scripts", t / "scripts")
        for d in ("boltrig", "docs", "tests", "deploy"):
            (t / d).mkdir(exist_ok=True)
        for f in ("Makefile", "pyproject.toml"):
            if (fixture_root / f).exists():
                shutil.copy(fixture_root / f, t / f)
        try:
            r = subprocess.run(
                [sys.executable, f"scripts/{script.name}"],
                cwd=t, capture_output=True, text=True, timeout=90,
            )
            return r.returncode, (r.stdout + r.stderr)
        except subprocess.TimeoutExpired:
            return 124, "timed out"


def self_test() -> int:
    """A sweep that hunts vacuous passes and has never been seen to catch one is the same defect,
    one level up - and a corpus where everything already refuses is exactly the state in which a
    broken sweep is indistinguishable from a working one."""
    rc = 0
    with tempfile.TemporaryDirectory() as tmp:
        fake = Path(tmp) / "repo"
        (fake / "scripts").mkdir(parents=True)
        (fake / "scripts" / "check_vacuous_fixture.py").write_text(
            "print('OK: everything is fine')\n"
        )
        # THE DISCRIMINATOR. Exit 0 is not the test, the PASS WORD is. A gate that exits 0 while
        # SAYING it checked nothing is honest and must not be flagged, or the sweep cries wolf on
        # every legitimate skip and gets switched off within the week.
        (fake / "scripts" / "check_honest_fixture.py").write_text(
            "print('SKIP: no corpus present, nothing was checked')\n"
        )

        code, out = empty_tree_verdict(fake / "scripts" / "check_vacuous_fixture.py", fake)
        vac = code == 0 and any(w in out for w in PASS_WORDS)
        print(f"  {'ok   ' if vac else 'FAIL '} a gate printing OK over nothing is caught")
        rc |= 0 if vac else 1

        code, out = empty_tree_verdict(fake / "scripts" / "check_honest_fixture.py", fake)
        honest = code == 0 and not any(w in out for w in PASS_WORDS)
        print(f"  {'ok   ' if honest else 'FAIL '} a gate saying it checked NOTHING is not flagged")
        rc |= 0 if honest else 1

    # THE POSITIVE CONTROL. The two cases above prove only that the verdict function discriminates;
    # the real corpus must pass, or the sweep is simply always red.
    real = [g for g in gates() if g.name not in NO_EMPTY_TREE_FORM]
    if not real:
        print("  FAIL  swept zero gates")
        return 1
    print(f"  ok    the real corpus has {len(real)} sweepable gate(s)")
    print("self-test: " + ("PASS" if rc == 0 else "FAIL"))
    return rc


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()

    found = gates()
    if not found:
        print("ERROR: swept ZERO gates - the list is wrong, and silence is not a pass.",
              file=sys.stderr)
        return 2

    print("vacuous-green sweep: every gate, pointed at a tree with no source")
    bad, checked = [], 0
    for g in found:
        if g.name in NO_EMPTY_TREE_FORM:
            print(f"  skip  {g.name:<34} {NO_EMPTY_TREE_FORM[g.name][:44]}...")
            continue
        code, out = empty_tree_verdict(g, ROOT)
        checked += 1
        if code == 0 and any(w in out for w in PASS_WORDS):
            bad.append((g.name, (out.strip().splitlines() or [""])[-1][:80]))
            print(f"  VACUOUS {g.name}", file=sys.stderr)
        else:
            last = (out.strip().splitlines() or [""])[-1][:44]
            print(f"  ok    {g.name:<34} refused (rc={code}): {last}")

    if checked == 0:
        print("ERROR: every gate was skipped - a sweep over nothing is the defect it is named for.",
              file=sys.stderr)
        return 2

    print()
    if bad:
        print(f"FAIL: {len(bad)} gate(s) report a pass over a tree they never read.", file=sys.stderr)
        for name, line in bad:
            print(f"  {name}: {line}", file=sys.stderr)
        print("\n  Use scripts/scan_guard.py::require_scanned, or make the gate assert its inputs\n"
              "  EXIST before it counts them. A pass condition of 'zero' is satisfied by absence.",
              file=sys.stderr)
        return 1

    print(f"OK: {checked} gate(s) swept, none passes over an empty tree.")
    print("Zero findings is not zero checkers. Only 5 of 18 gates use scan_guard; the other 13\n"
          "refuse by accident of how each is written, and this is what holds them to it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
