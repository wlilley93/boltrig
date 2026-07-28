"""The accepted-advisory ledger's expiry machinery (dependency-policy item 6).

2026-VJS-CC-BOLTRIG-SUPPLY-CHAIN-ADVISORY-ACCEPTANCE-001 D2: both acceptances
on the backup image's rclone binary (GHSA-hrxh-6v49-42gf, CVE-2026-56852,
ecosystem go) are recorded in ``docs/security/accepted-advisories.json``, and
the record has teeth - ``scripts/python_audit.py`` fails BEFORE pip-audit runs
on any expired or unparseable entry, in EVERY ecosystem, so a stale acceptance
fails the review instead of silently suppressing.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest

from scripts import python_audit


def _write_ledger(entries) -> Path:
    """A throwaway ledger INSIDE the repo: python_audit's failure path prints
    the ledger relative to cwd, so a /tmp path would raise there instead of
    exercising the expiry gate."""
    ledger = Path.cwd() / f".test-ledger-{uuid.uuid4().hex[:8]}.json"
    ledger.write_text(json.dumps({"version": 1, "accepted": entries}))
    return ledger


def _entry(ident, ecosystem, *, expires=None):
    return {
        "id": ident,
        "package": "golang.org/x/text",
        "version": "0.38.0",
        "owner": "release-engineering",
        "expires": expires or str(date.today() + timedelta(days=30)),
        "no_fix_available": True,
        "reachability": "test",
        "compensating_control": "test",
        "reason": "test",
        "ecosystem": ecosystem,
    }


@pytest.mark.security
@pytest.mark.invariant("IAC-006")
def test_an_expired_entry_fails_before_the_audit_in_every_ecosystem(
    monkeypatch, capsys
) -> None:
    """SUPPLY-CHAIN-ADVISORY-ACCEPTANCE-001 D2: expiry has teeth everywhere -
    a GO entry (never handed to pip-audit) is still expiry-checked, so the
    CVE-2026-56852 / GHSA-hrxh-6v49-42gf records cannot rot unnoticed."""
    yesterday = str(date.today() - timedelta(days=1))
    for ecosystem in ("python", "go", "npm"):
        ledger = _write_ledger([_entry("CVE-0000-00000", ecosystem, expires=yesterday)])
        monkeypatch.setattr(python_audit, "_LEDGER", ledger)
        try:
            assert python_audit.main(["requirements-lock.txt"]) == 1
            assert "expired" in capsys.readouterr().out
        finally:
            ledger.unlink()


@pytest.mark.security
@pytest.mark.invariant("IAC-006")
def test_only_python_entries_become_ignore_vuln_flags(monkeypatch) -> None:
    """One ledger for every ecosystem, but only Python entries mean anything
    to pip-audit: a live go entry is reviewed for expiry, never suppressed."""
    ledger = _write_ledger([
        _entry("PYSEC-0000-0000", "python"),
        _entry("CVE-0000-00000", "go"),
    ])
    monkeypatch.setattr(python_audit, "_LEDGER", ledger)
    try:
        ignored, expired = python_audit._load(date.today())
        assert ignored == ["PYSEC-0000-0000"]
        assert expired == []
    finally:
        ledger.unlink()


@pytest.mark.security
@pytest.mark.invariant("IAC-006")
def test_the_shipped_ledger_is_live_and_wellformed() -> None:
    """The real ledger: every entry carries the item 6 record and none is
    expired today - the state D2 requires of both go acceptances."""
    entries = json.loads(python_audit._LEDGER.read_text())["accepted"]
    assert entries
    for entry in entries:
        for key in ("id", "package", "owner", "expires", "reachability",
                    "compensating_control", "reason", "ecosystem"):
            assert entry.get(key), f"{entry.get('id')}: missing {key}"
    _, expired = python_audit._load(date.today())
    assert expired == []
