#!/usr/bin/env python3
"""Refuse a supply-chain exclusion list that cannot do what it says.

WHY THIS EXISTS. The former console workspace carried two `minimumReleaseAgeExclude`
entries for the same package, `@wlilley93/boltrig-web-sdk@0.1.0` and `@0.1.1`.
pnpm evaluates that list by FIRST MATCHING NAME PATTERN and consults no later
entry for the package, so the 0.1.0 entry - stale, not even resolved by the
lockfile, and long past the 24h window it would have exempted - shadowed the
0.1.1 entry and every UI pull request failed `pnpm install --frozen-lockfile`
with ERR_PNPM_MINIMUM_RELEASE_AGE_VIOLATION.

The shape of the defect is the dangerous one: the file LOOKED like it granted
the exemption. Reading it told you the opposite of what pnpm did with it, and
the diagnosis that followed ("the verifier ignores this list") was wrong for
most of a day.

Two rules, both mechanical:

  1. At most ONE entry per package name. A second is not additive - it is inert,
     and it silently disables the first.
  2. Every entry must pin a version. A bare name or a `*` exempts whatever is
     published under that name in future, which is an exemption granted to
     whoever can publish, not to an artefact anyone has reviewed.

Exit 0 = conforming. Exit 1 = refused, with the offending entries named.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Deliberately a line-oriented parse rather than a YAML load: this must run in a
# pre-push hook and in CI before any dependency is installed, so it cannot import
# PyYAML. The keys it reads are flat string sequences; nothing here needs a real
# YAML parser, and requiring one would be the reason the gate is skipped.
LIST_KEYS = ("minimumReleaseAgeExclude", "trustPolicyExclude")

# '@scope/name@1.2.3' -> ('@scope/name', '1.2.3'); 'pkg@1.2.3' -> ('pkg', '1.2.3')
ENTRY = re.compile(r"^(?P<name>@?[^@]+(?:/[^@]+)?)@(?P<version>[^@]+)$")


def parse_lists(text: str) -> dict[str, list[tuple[int, str]]]:
    """Return {key: [(line_no, entry), ...]} for each exclusion list present."""
    found: dict[str, list[tuple[int, str]]] = {}
    current: str | None = None
    for line_no, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key = stripped.split(":", 1)[0]
        if key in LIST_KEYS and stripped.endswith(":"):
            current = key
            found.setdefault(current, [])
            continue
        if current is None:
            continue
        if stripped.startswith("- "):
            found[current].append((line_no, stripped[2:].strip().strip("'\"")))
            continue
        # Any other non-indented key ends the list.
        if not raw.startswith((" ", "\t")):
            current = None
    return found


def check(path: Path) -> list[str]:
    problems: list[str] = []
    lists = parse_lists(path.read_text())

    for key, entries in lists.items():
        by_name: dict[str, list[tuple[int, str]]] = {}
        for line_no, entry in entries:
            match = ENTRY.match(entry)
            if not match or "*" in entry:
                problems.append(
                    f"{path}:{line_no}: {key} entry {entry!r} does not pin a single version.\n"
                    f"    A name-only or wildcard entry exempts whatever is published under that\n"
                    f"    name in future - that is an exemption granted to whoever can publish,\n"
                    f"    not to an artefact anyone reviewed. Write '<package>@<version>'."
                )
                continue
            by_name.setdefault(match.group("name"), []).append((line_no, entry))

        for name, hits in by_name.items():
            if len(hits) > 1:
                where = ", ".join(f"line {ln} ({e})" for ln, e in hits)
                problems.append(
                    f"{path}: {key} has {len(hits)} entries for {name!r}: {where}.\n"
                    f"    pnpm matches this list FIRST-PATTERN-WINS and ignores every later\n"
                    f"    entry for the same package, so all but the first are INERT and the\n"
                    f"    first silently decides. Keep exactly one, for the version the\n"
                    f"    lockfile actually resolves."
                )
    return problems


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    targets = [p for p in (root / "apps" / "worker" / "pnpm-workspace.yaml",) if p.exists()]
    if not targets:
        # Nothing to check is not the same as a pass. Say so rather than exit 0
        # quietly: a gate that silently passes when its subject is missing is how
        # a check stops checking without anyone noticing.
        print("check-release-age-exclusions: SKIP - no pnpm-workspace.yaml found", file=sys.stderr)
        return 0

    problems: list[str] = []
    for target in targets:
        problems.extend(check(target))

    if problems:
        print("REFUSED: supply-chain exclusion list cannot do what it says\n", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}\n", file=sys.stderr)
        return 1

    total = sum(len(v) for t in targets for v in parse_lists(t.read_text()).values())
    print(f"check-release-age-exclusions: OK ({total} exclusion entries, one per package, all version-pinned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
