#!/usr/bin/env python3
"""A security override that did not reach the lock is not an override.

`deploy/browser-cli-overrides.txt` exists for one reason: browser-use resolves transitive
releases with known advisories, and each line forces a fixed version. Every entry in it is a
CVE remedy. The file the image actually installs is `deploy/browser-cli-requirements.txt`, a
hash-locked artefact compiled FROM the overrides by `uv pip compile`.

THE DEFECT THIS EXISTS FOR, and it was live on `main` on 2026-07-27. Dependabot raised the
aiohttp override from 3.14.1 to 3.14.3 and edited only the overrides file. Nothing recompiles
the lock, and nothing compared the two, so the lock kept installing 3.14.1: the override was
INERT and every check was green. The remedy said one thing and the image did another, which is
this repository's oldest defect shape wearing dependency clothes.

WHY THIS CHECK AND NOT A RECOMPILE. Recompiling in CI would answer a bigger question and would
need the network to do it, and a gate that needs the network is a gate that goes red for
reasons unrelated to the code until somebody switches it off. This is hermetic: for every
`name==version` pin in an overrides file, the compiled lock beside it must pin that same name
at that same version. That is exactly the property an override HAS to have to be an override,
and reading two committed files establishes it with no resolver and no network.

WHAT IT DOES NOT ESTABLISH. That the lock is otherwise a faithful compile of the `.in` file, or
that the pinned versions are free of advisories. The first needs a resolver, the second needs an
advisory feed, and both are the scanners' job. This answers one question completely: did the
override take.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Each pair is (overrides file, the lock compiled from it). Adding an override file without
# adding it here would make the new file unchecked, so the pairing is asserted below against
# the compile command the lock records in its own header.
PAIRS = [
    (ROOT / "deploy" / "browser-cli-overrides.txt",
     ROOT / "deploy" / "browser-cli-requirements.txt"),
]

_PIN = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*==\s*([^\s\\;#]+)")


def pins(path: Path) -> dict[str, str]:
    """name -> version, for every `name==version` line. Comments and blanks ignored."""
    found: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        m = _PIN.match(line)
        if m:
            # PEP 503 normalisation: `Pillow` and `pillow` are one project, and a lock written
            # by one tool and an override written by a human will not agree on the spelling.
            found[re.sub(r"[-_.]+", "-", m.group(1)).lower()] = m.group(2)
    return found


def main() -> int:
    failures: list[str] = []
    checked = 0

    for overrides, lock in PAIRS:
        if not overrides.exists() or not lock.exists():
            failures.append(f"missing {overrides.name} or {lock.name}")
            continue

        # The lock records the exact command that produced it. If that command does not name
        # this overrides file, the pairing above is wrong and every comparison below is
        # answering a question about two unrelated files.
        header = "\n".join(lock.read_text(encoding="utf-8").splitlines()[:5])
        if overrides.relative_to(ROOT).as_posix() not in header:
            failures.append(
                f"{lock.relative_to(ROOT)} does not record {overrides.name} in its compile "
                "command, so this pairing is asserted rather than observed"
            )
            continue

        want, got = pins(overrides), pins(lock)
        if not want:
            failures.append(
                f"{overrides.relative_to(ROOT)} declares no pins. An empty override file is "
                "either a mistake or a remedy someone deleted; either way it is not a pass."
            )
            continue

        for name, version in sorted(want.items()):
            checked += 1
            actual = got.get(name)
            if actual is None:
                failures.append(
                    f"{name}=={version} is overridden in {overrides.name} and appears in "
                    f"{lock.name} not at all. The override cannot have taken."
                )
            elif actual != version:
                failures.append(
                    f"{name}: {overrides.name} says {version}, {lock.name} installs {actual}. "
                    "The override is INERT - the image ships the version it was raised to "
                    f"replace. Recompile: see the command in {lock.name}'s header."
                )

    print(f"override pins checked: {checked} across {len(PAIRS)} file pair(s)")
    if failures:
        print()
        for f in failures:
            print(f"  - {f}")
        print("\nRESULT: FAIL - an override did not reach the lock the image installs.")
        return 1
    print("\nRESULT: PASS - every override pin is the version the lock installs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
