#!/usr/bin/env python3
"""Audit the shipped Python graph, honouring EXPIRING accepted advisories.

`docs/dependency-policy.md` ("Required verification", item 6) requires that any
accepted advisory record reachability, owner, expiry and a compensating control,
and that an expired exception FAILS. A bare `--ignore-vuln` flag in the Makefile
cannot expire, so the ledger lives in `docs/security/accepted-advisories.json`
and this wrapper enforces it:

  - every non-expired entry is passed to pip-audit as `--ignore-vuln`;
  - an entry whose `expires` date has passed fails HERE, before pip-audit runs,
    so a stale suppression cannot quietly outlive its review;
  - the accepted set is always printed, so a green audit still says out loud
    what it is not checking.

Accept an advisory only when there is no fixed upstream release. If a fix
exists, take the fix.

Usage: scripts/python_audit.py <requirements-lock.txt> [more locks...]
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

_LEDGER = Path(__file__).resolve().parents[1] / "docs" / "security" / "accepted-advisories.json"


def _load(today: date) -> tuple[list[str], list[str]]:
    """Return (ignored ids, expired descriptions) from the ledger."""
    if not _LEDGER.exists():
        return [], []
    entries = json.loads(_LEDGER.read_text()).get("accepted") or []
    ignored: list[str] = []
    expired: list[str] = []
    for entry in entries:
        ident = str(entry.get("id") or "").strip()
        if not ident:
            continue
        raw = str(entry.get("expires") or "").strip()
        try:
            expires = date.fromisoformat(raw)
        except ValueError:
            expired.append(f"{ident}: unreadable expires={raw!r}")
            continue
        if expires < today:
            expired.append(
                f"{ident} ({entry.get('package')}) expired {raw}, "
                f"owner={entry.get('owner')}"
            )
        else:
            ignored.append(ident)
            print(
                f"  accepted: {ident} {entry.get('package')}=={entry.get('version')} "
                f"until {raw} (owner {entry.get('owner')})"
            )
    return ignored, expired


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python_audit.py <requirements lock> [...]", file=sys.stderr)
        return 2
    print(f"python-audit: {len(argv)} lock file(s); accepted advisories:")
    ignored, expired = _load(date.today())
    if not ignored:
        print("  (none)")
    if expired:
        print("\nFAIL: expired accepted advisories must be re-reviewed or fixed:")
        for line in expired:
            print(f"  - {line}")
        print(f"\nEdit {_LEDGER.relative_to(Path.cwd())} - take the upstream fix if one now exists.")
        return 1
    command = [
        sys.executable, "-m", "pip_audit",
        "--strict", "--progress-spinner", "off", "--require-hashes",
    ]
    for ident in ignored:
        command += ["--ignore-vuln", ident]
    for lock in argv:
        command += ["-r", lock]
    return subprocess.call(command)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
