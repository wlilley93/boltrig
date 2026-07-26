"""The three claim gates added on 2026-07-26, bound so they cannot go quiet.

A gate that nobody runs is worth exactly as much as the prose it replaced, and
each of these exists because of a defect that had already shipped:

  * prose-references - `boltrig/emotion/relay.py` said it superseded a module the
    same commit deleted, and the founding consolidation ruling that
    `docs/invariants.md` calls the canonical source of every K-* id pointed at a
    register path that has never existed in this repository's history.
  * gate-coverage - `make quality` calls itself "the complete local release
    gate" while two of its components, migration parity and the secure
    production-doctor fixture, ran in no CI job at all.
  * health-claims - a client tenant sat at /readyz 503 for about forty minutes
    on an unapplied schema head while `docker ps` reported the kernel healthy
    the whole time.

Following NFR-MNT-01's precedent, each gate is bound by asserting it is clean on
the real tree. The health gate's waiver loader gets seeded failures too, because
"an expired or reasonless exemption is itself a failure" is the claim most likely
to rot: a waiver is exactly the thing people stop reading.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from scripts import check_gate_coverage, check_health_claims, check_prose_references

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.invariant("NFR-MNT-03")
def test_every_reference_the_record_makes_still_resolves(capsys) -> None:
    """Renaming or deleting a thing must break every record that names it."""
    assert check_prose_references.main() == 0, capsys.readouterr().out


@pytest.mark.invariant("NFR-MNT-04")
def test_every_compose_manifest_and_release_component_is_actually_reached(capsys) -> None:
    """A gate input nothing loads, and an aggregate that skips its own parts."""
    assert check_gate_coverage.main() == 0, capsys.readouterr().out


@pytest.mark.invariant("NFR-MNT-05")
def test_no_service_reports_healthy_while_unable_to_serve(capsys) -> None:
    """Or is recorded, with an owner and an expiry, as unable to tell."""
    assert check_health_claims.main() == 0, capsys.readouterr().out


def _write_exemptions(tmp_path: Path, monkeypatch, entry: dict) -> Path:
    path = tmp_path / "health-claim-exemptions.json"
    path.write_text(json.dumps({"exemptions": {"kernel": entry}}), encoding="utf-8")
    monkeypatch.setattr(check_health_claims, "EXEMPTIONS", path)
    return path


@pytest.mark.invariant("NFR-MNT-05")
def test_a_waiver_with_no_reason_is_itself_a_failure(tmp_path, monkeypatch) -> None:
    _write_exemptions(tmp_path, monkeypatch, {"owner": "platform", "reason": "   "})
    valid, problems = check_health_claims.load_exemptions()
    assert valid == {}
    assert any("reason" in p for p in problems), problems


@pytest.mark.invariant("NFR-MNT-05")
def test_a_waiver_with_no_owner_is_itself_a_failure(tmp_path, monkeypatch) -> None:
    _write_exemptions(tmp_path, monkeypatch, {"reason": "a real reason"})
    valid, problems = check_health_claims.load_exemptions()
    assert valid == {}
    assert any("owner" in p for p in problems), problems


@pytest.mark.invariant("NFR-MNT-05")
def test_an_expired_waiver_stops_waiving(tmp_path, monkeypatch) -> None:
    """The whole point of the expiry: a stale waiver is a claim nobody checks."""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    _write_exemptions(
        tmp_path, monkeypatch,
        {"owner": "platform", "reason": "deferred", "expires": yesterday},
    )
    valid, problems = check_health_claims.load_exemptions()
    assert valid == {}
    assert any("expired" in p for p in problems), problems


@pytest.mark.invariant("NFR-MNT-05")
def test_the_repositorys_own_waivers_are_well_formed(tmp_path, monkeypatch) -> None:
    """The live file, not a fixture: two open debts, each owned and dated."""
    valid, problems = check_health_claims.load_exemptions()
    assert problems == []
    assert set(valid) == {"kernel", "fleet-worker"}
    for name, entry in valid.items():
        assert entry["expires"], f"{name}: an open debt with no expiry never comes back"
