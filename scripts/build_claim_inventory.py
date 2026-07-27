#!/usr/bin/env python3
"""Tier 0 of GOAL-claims-must-be-load-bearing: enumerate the claims.

The goal document called this "the piece nobody has done and everything else depends on it",
and then, forty lines later, described "the inventory's UNVERIFIED column" as partly worked.
There was no inventory and there never had been. A document about claims being load-bearing
carrying a false claim about its own foundation is the defect it exists to catch, one level up.

WHY THIS IS A SCRIPT AND NOT A PAGE. A hand-written census is accurate for one afternoon.
There are over a thousand claim-bearing statements in `boltrig/` alone and they are written
faster than they are read, so the only honest form is a GENERATED artefact plus a ratchet:
`docs/claim-inventory.tsv` is the census, `scripts/check_claim_inventory.py` refuses to let the
uncovered count rise, and neither can be true on Tuesday and quietly false on Friday.

WHAT A CLAIM IS, HERE. A sentence in a docstring, a comment, or a compose file that ASSERTS
something about behaviour: that a thing never happens, always happens, cannot happen, fails
closed, is the only path, is append-only. The phrase list is closed and deliberately narrow.
Every claim is then classified by WHAT IT NAMES, because that is the only thing a machine can
check:

  SUBJECT-REACHED   the claim code-quotes a symbol defined under boltrig/, and that symbol is
                    referenced by production code. The thing described exists and runs. This is
                    NOT proof the claim is true; it is proof the claim has a live subject, and
                    it is exactly the check that would have caught RedisCounter.
  SUBJECT-ABSENT    the claim code-quotes a symbol defined under boltrig/ that NOTHING outside
                    its own definition mentions. The subject is dead and the claim outlived it.
                    A finding, always.
  SUBJECT-EXTERNAL  the claim names something outside boltrig/ (a third-party symbol, a path,
                    an env var). `prose-references` covers the paths and env vars.
  NO-SUBJECT        the claim asserts behaviour and names nothing a machine can resolve.

NO-SUBJECT is the residue, and it is the whole point of the exercise. Two of the eleven
original defects lived there: `docker-compose.yml` attributed "rate-limit + ephemeral counters"
to redis while nothing constructed RedisCounter, and fourteen docstrings said credentials were
"never logged" without naming the mechanism that made it so. Neither names a symbol, so no
symbol-aware gate can see either.

THE HONEST LIMIT, and it is the same one the goal document states: this cannot know whether a
claim is TRUE. It knows whether the claim has a subject and whether that subject is reached.
That is the difference between the eleven defects in the evidence table and eleven silent ones,
and it is not more than that.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "claim-inventory.tsv"


def tracked(pattern: str) -> list[Path]:
    """Files matching a pathspec that git TRACKS. The source set, and not a directory walk.

    This function exists because the first version walked the filesystem and the census could
    only regenerate on one machine. `docker-compose.override.yml` is gitignored and holds local
    development config; it contributed two rows here and none in CI, so the gate that measures
    environment-dependent claims was itself environment-dependent. Tier 3 of this goal is
    exactly that family, and it arrived inside the tool measuring it.

    A fallback to `rglob` when git is unavailable was considered and refused: a fallback that
    changes the answer is the same defect wearing a different hat. Without git this raises.
    """
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z", "--", pattern],
        capture_output=True, check=True, text=True,
    ).stdout
    # `.exists()` because `git ls-files` lists a tracked path even when the working tree has
    # deleted it and the deletion is not yet staged. A half-finished deletion is not a source.
    return sorted(p for p in (ROOT / name for name in out.split("\0") if name) if p.exists())

# Closed, and narrow on purpose. An earlier draft included "should" and "handles", which made
# every ordinary explanatory comment a claim and buried the four hundred that matter. A claim
# is an assertion someone could be WRONG about, not a description.
ASSERTION = re.compile(
    r"(?<![\w-])("
    r"never|always|must not|must never|may not|cannot|can never|"
    r"is the only|the only (?:caller|path|place|writer|way)|"
    r"fails? closed|fail-closed|append-only|tamper-evident|"
    r"guarantee[sd]?|impossible|refuses|forbidden|"
    r"no caller|nothing (?:constructs|calls|reads|writes|invokes)"
    r")(?![\w-])",
    re.IGNORECASE,
)

# WHAT MAKES A CLAIM LOAD-BEARING. The goal document's closing ratchet is "the number of
# unbound LOAD-BEARING claims may only decrease", and a residue of nine hundred undifferentiated
# sentences cannot be ratcheted, only despaired at. So a claim is weighed by what a false
# version would COST, which the document states directly: "a security control's description
# outranks a comment about a variable name".
#
# The vocabulary below is the closed list of things whose description is a security control.
# It is deliberately about SUBJECT MATTER and not about tone: "the token is never logged" is
# load-bearing whether it is written confidently or not, and "the cache is never stale" is not,
# however emphatically it is put.
SECURITY_SUBJECT = re.compile(
    r"(?<![\w-])("
    r"secret|credential|password|token|bearer|api[- ]?key|"
    r"tenant|cross-tenant|isolation|leak|leaked|disclos\w*|redact\w*|scrub\w*|"
    r"authoris\w*|authoriz\w*|permission|grant|scope[ds]?|privilege|escalat\w*|"
    r"audit|append-only|tamper|chain|"
    r"pii|erasure|retention"
    r")(?![\w-])",
    re.IGNORECASE,
)

# ``sweep_run_scoped`` or `db.execute_write`. The CODE-QUOTED narrowing is inherited from
# check_unwired_claims.py and for the same reason: matching bare words made "consume",
# "dispatch", "push" and "stop" look advertised, because English uses them.
CODE_QUOTED = re.compile(r"``([A-Za-z_][\w.]*)``|`([A-Za-z_][\w.]*)`")


def _defined_symbols(pkg: Path) -> set[str]:
    """Every class and function name defined under the package."""
    names: set[str] = set()
    for path in tracked(f"{pkg.name}/**/*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(node.name)
    return names


def _reference_counts(pkg: Path) -> dict[str, int]:
    """How many times each bare name appears under the package, definitions included.

    A count of 1 means the definition and nothing else, which is precisely the RedisCounter
    shape: one grep, one hit, the `class` statement itself.
    """
    counts: dict[str, int] = {}
    word = re.compile(r"[A-Za-z_][\w]*")
    for path in tracked(f"{pkg.name}/**/*.py"):
        for name in word.findall(path.read_text(encoding="utf-8", errors="replace")):
            counts[name] = counts.get(name, 0) + 1
    return counts


def _classify(text: str, defined: set[str], counts: dict[str, int]) -> tuple[str, str]:
    """(classification, subject) for one claim."""
    quoted = [a or b for a, b in CODE_QUOTED.findall(text)]
    # A qualified reference names its tail: ``db.execute_write`` names execute_write.
    resolved = [(q, q.rsplit(".", 1)[-1]) for q in quoted]
    local = [(q, tail) for q, tail in resolved if tail in defined]
    if local:
        # Report the WEAKEST subject: a claim naming three symbols is only as well-founded as
        # the one nothing reaches.
        worst = min(local, key=lambda qt: counts.get(qt[1], 0))
        return ("SUBJECT-ABSENT" if counts.get(worst[1], 0) <= 1 else "SUBJECT-REACHED"), worst[0]
    if quoted:
        return "SUBJECT-EXTERNAL", quoted[0]
    return "NO-SUBJECT", ""


def _weight(text: str) -> str:
    """LOAD-BEARING where a false version costs a security control, ORDINARY otherwise.

    The distinction is what makes the residue a work QUEUE rather than a number. Ranked this
    way, the uncovered claims sort into a few hundred that describe controls and several
    hundred that describe conveniences, and only the first list is worth a gate each.
    """
    return "LOAD-BEARING" if SECURITY_SUBJECT.search(text) else "ORDINARY"


def _first_sentence(text: str) -> str:
    """One line, bounded, so the TSV stays a census and not a copy of the source."""
    flat = " ".join(text.split())
    for end in (". ", "; "):
        if end in flat[:220]:
            flat = flat[: flat.index(end) + 1]
            break
    return flat[:220]


def _python_claims(pkg: Path, defined: set[str], counts: dict[str, int]) -> list[dict]:
    rows: list[dict] = []
    for path in tracked(f"{pkg.name}/**/*.py"):
        rel = path.relative_to(ROOT).as_posix()
        src = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                continue
            doc = ast.get_docstring(node)
            if not doc or not ASSERTION.search(doc):
                continue
            kind, subject = _classify(doc, defined, counts)
            rows.append({
                "weight": _weight(doc),
                "source": "docstring",
                "location": f"{rel}:{getattr(node, 'lineno', 1)}",
                "classification": kind,
                "subject": subject,
                "claim": _first_sentence(doc),
            })
        for i, line in enumerate(src.splitlines(), start=1):
            stripped = line.strip()
            if not stripped.startswith("#") or not ASSERTION.search(stripped):
                continue
            kind, subject = _classify(stripped, defined, counts)
            rows.append({
                "weight": _weight(stripped),
                "source": "comment",
                "location": f"{rel}:{i}",
                "classification": kind,
                "subject": subject,
                "claim": _first_sentence(stripped.lstrip("# ")),
            })
    return rows


def _compose_claims(defined: set[str], counts: dict[str, int]) -> list[dict]:
    """Comments in compose files that attribute behaviour to a service.

    This is the source that mattered most and had no gate at all: `docker-compose.yml`
    attributed "rate-limit + ephemeral counters" to redis, `ratelimit.py` said "the production
    back end is Redis", and `readiness.py` made Redis required, while nothing constructed
    RedisCounter. Three records asserting a control the deployment did not have, and one of
    them was here.
    """
    rows: list[dict] = []
    for path in tracked("docker-compose*.yml") + tracked("deploy/**/*compose*.yml"):
        rel = path.relative_to(ROOT).as_posix()
        for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            stripped = line.strip()
            if not stripped.startswith("#") or not ASSERTION.search(stripped):
                continue
            kind, subject = _classify(stripped, defined, counts)
            rows.append({
                "weight": _weight(stripped),
                "source": "compose",
                "location": f"{rel}:{i}",
                "classification": kind,
                "subject": subject,
                "claim": _first_sentence(stripped.lstrip("# ")),
            })
    return rows


def build() -> list[dict]:
    pkg = ROOT / "boltrig"
    defined = _defined_symbols(pkg)
    counts = _reference_counts(pkg)
    rows = _python_claims(pkg, defined, counts) + _compose_claims(defined, counts)
    rows.sort(key=lambda r: (r["weight"] != "LOAD-BEARING", r["classification"], r["location"]))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="do not write; report whether the committed inventory is current")
    args = parser.parse_args()

    rows = build()
    header = ["weight", "classification", "source", "location", "subject", "claim"]
    lines = ["\t".join(header)]
    for r in rows:
        lines.append("\t".join(r[h].replace("\t", " ") for h in header))
    body = "\n".join(lines) + "\n"

    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != body:
            print("STALE: docs/claim-inventory.tsv is not what the sources now say.",
                  file=sys.stderr)
            print("       Regenerate with `make claim-inventory`.", file=sys.stderr)
            return 1
        print(f"claim inventory current: {len(rows)} claims")
        return 0

    OUT.write_text(body, encoding="utf-8")
    tally: dict[tuple[str, str], int] = {}
    for r in rows:
        key = (r["weight"], r["classification"])
        tally[key] = tally.get(key, 0) + 1
    print(f"wrote {OUT.relative_to(ROOT)}: {len(rows)} claims")
    for (w, c) in sorted(tally):
        print(f"  {w:<13} {c:<17} {tally[(w, c)]}")
    residue = sum(
        1 for r in rows
        if r["weight"] == "LOAD-BEARING" and r["classification"] == "NO-SUBJECT"
    )
    print(f"\nTHE RATCHET: {residue} load-bearing claims name nothing a machine can resolve.")
    absent = [r for r in rows if r["classification"] == "SUBJECT-ABSENT"]
    if absent:
        print("\nSUBJECT-ABSENT - the claim outlived the thing it names:")
        for r in absent:
            print(f"  {r['location']}  {r['subject']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
