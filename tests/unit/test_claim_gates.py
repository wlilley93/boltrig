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

from scripts import (
    check_gate_coverage,
    check_health_claims,
    check_order_directives,
    check_prose_references,
)

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
    """The live file, not a fixture. ZERO open debts.

    It was two, and both were discharged on 2026-07-26 rather than renewed: the
    kernel probes /readyz, and the fleet worker probes `boltrig fleet-health`,
    which reads back the signed tool receipt it already published. This assertion
    is the ratchet - putting a service back has to be a deliberate edit to a test,
    not a quiet line in a JSON file.
    """
    valid, problems = check_health_claims.load_exemptions()
    assert problems == []
    assert valid == {}, (
        "a health waiver was added; say which service, and why its signal cannot "
        "see an outage, in the same change"
    )
    for name, entry in valid.items():
        assert entry["expires"], f"{name}: an open debt with no expiry never comes back"


# --- the gates' own floors ----------------------------------------------------
@pytest.mark.invariant("NFR-MNT-06")
def test_a_scan_that_finds_nothing_is_a_failure_not_a_pass() -> None:
    """Every gate here globs a tree. An empty glob has no offenders, so it prints
    PASS having verified nothing - one directory rename, one sparse checkout, one
    narrow build context away, and green means "could not look"."""
    from scripts import scan_guard

    assert scan_guard.require_scanned([1, 2], "things") == [1, 2]
    with pytest.raises(SystemExit) as raised:
        scan_guard.require_scanned([], "compose manifests under deploy/")
    assert raised.value.code == 1

    with pytest.raises(SystemExit):
        scan_guard.require_scanned([1], "sources", minimum=50)


@pytest.mark.invariant("NFR-MNT-06")
def test_the_unwired_waiver_file_can_be_held_to(tmp_path, monkeypatch) -> None:
    """A waiver with no owner or no expiry is eternal and unowned, which is the
    shape this programme exists to remove - and this file had neither until the
    day after it was written."""
    from scripts import check_unwired_claims

    def _write(entry: dict) -> Path:
        path = tmp_path / "allow.json"
        path.write_text(json.dumps({"allow": {"thing": entry}}), encoding="utf-8")
        return path

    good = {"owner": "x-maintainers", "expires": "2099-12-31", "reason": "a real one"}
    allow, problems = check_unwired_claims.load_allow(_write(good))
    assert problems == [] and allow == {"thing": "a real one"}

    for missing, word in (
        ({**good, "owner": " "}, "owner"),
        ({**good, "reason": ""}, "reason"),
        ({k: v for k, v in good.items() if k != "expires"}, "expiry"),
        ({**good, "expires": "2020-01-01"}, "expired"),
    ):
        allow, problems = check_unwired_claims.load_allow(_write(missing))
        assert allow == {} and any(word in p for p in problems), (missing, problems)


@pytest.mark.invariant("NFR-MNT-06")
def test_the_repositorys_own_unwired_waivers_are_well_formed() -> None:
    from scripts import check_unwired_claims

    allow, problems = check_unwired_claims.load_allow(check_unwired_claims.ALLOW_FILE)
    assert problems == []
    assert allow, "the waiver file exists, so it should hold waivers"


@pytest.mark.invariant("NFR-MNT-06")
def test_the_operators_shell_cannot_colour_a_test() -> None:
    """No product-behaviour variable survives into a test from the launching shell.

    33 modules under boltrig/ read os.environ at CALL time, so an exported
    BOLTRIG_PRODUCTION or DATABASE_URL silently decides which branch a test takes.
    A test named "refuses under a production signal" can then pass because the
    SHELL set the signal. Neither the pass nor the reason appears in the output.

    Run `BOLTRIG_PRODUCTION=1 pytest tests/unit/test_claim_gates.py` to see this
    fail with the autouse fence in tests/conftest.py disabled, and pass with it on.
    """
    import os

    from tests.conftest import _ENV_KEEP, _ENV_STRIP_EXACT, _ENV_STRIP_PREFIXES

    leaked = sorted(
        name for name in os.environ
        if name not in _ENV_KEEP
        and (name.startswith(_ENV_STRIP_PREFIXES) or name in _ENV_STRIP_EXACT)
    )
    assert leaked == [], (
        f"the launching shell reached the test: {leaked}. Either the fence in "
        "tests/conftest.py stopped covering these, or a new prefix needs adding."
    )


# --- the order-binding gate --------------------------------------------------
@pytest.mark.invariant("NFR-MNT-03")
def test_every_binding_court_directive_is_bound_or_recorded(capsys) -> None:
    assert check_order_directives.main() == 0, capsys.readouterr().out


@pytest.mark.invariant("NFR-MNT-03")
def test_the_order_readers_shortcut_agrees_with_a_real_yaml_parser() -> None:
    """The gate ships stdlib-only and reads orders with an indentation scanner.

    That shortcut is only safe while it AGREES with the parser it is standing in
    for. The invariant catalogue is the cautionary case: it was read by a regex
    reader for months and did not actually parse as the YAML its name claimed.
    So the shortcut is held to PyYAML's answer on every real order in the tree,
    not on a fixture, because a fixture would only prove the reader agrees with
    itself.
    """
    import yaml

    paths = sorted(check_order_directives.ORDERS.glob("*.yaml"))
    assert paths, "scanned nothing: no order files to compare readers on"
    for path in paths:
        truth = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        mine = check_order_directives.parse_order(path)
        assert mine["id"] == (truth.get("id") or ""), path.name
        assert mine["status"] == (truth.get("status") or ""), path.name
        assert mine["citation"] == str(truth.get("citation") or ""), path.name
        expected = [str(d.get("id")) for d in (truth.get("directives") or [])]
        assert mine["directives"] == expected, (
            f"{path.name}: stdlib reader saw {mine['directives']}, YAML saw {expected}"
        )


# --- an override that did not reach the lock is not an override -----------------------------
#
# The twelfth gate, 2026-07-27. Every line of deploy/browser-cli-overrides.txt is a CVE remedy,
# and dependabot raised the aiohttp pin there while editing nothing else. Nothing recompiles the
# hash-locked file the image installs, and nothing compared them, so main carried an override
# saying 3.14.3 and a lock installing 3.14.1. Every check was green.


def test_every_override_pin_is_the_version_the_lock_installs(capsys) -> None:
    """The real tree."""
    from scripts import check_override_locks

    assert check_override_locks.main() == 0, capsys.readouterr().out


def test_an_inert_override_is_reported_rather_than_passed(tmp_path, monkeypatch, capsys) -> None:
    """Seeded with exactly the state main was in: the override raised, the lock not recompiled.

    The message has to say which way round it is. "These files disagree" leaves a reader to
    work out whether the remedy or the shipped version is the stale one, and under time
    pressure that is the moment somebody edits the wrong file.
    """
    from scripts import check_override_locks

    overrides = tmp_path / "o-overrides.txt"
    lock = tmp_path / "o-requirements.txt"
    overrides.write_text("aiohttp==3.14.3\n", encoding="utf-8")
    lock.write_text(
        f"# uv pip compile --overrides {overrides} -o {lock}\naiohttp==3.14.1\n", encoding="utf-8"
    )
    monkeypatch.setattr(check_override_locks, "ROOT", tmp_path)
    monkeypatch.setattr(check_override_locks, "PAIRS", [(overrides, lock)])

    assert check_override_locks.main() == 1
    out = capsys.readouterr().out
    assert "INERT" in out and "3.14.3" in out and "3.14.1" in out


def test_a_pairing_the_lock_does_not_confirm_is_refused(tmp_path, monkeypatch, capsys) -> None:
    """The pairing must be OBSERVED, not asserted.

    A lock records the exact `uv pip compile` command that produced it. If that command does not
    name the overrides file this script compares it against, every comparison below is answering
    a question about two unrelated files, and answering it green.
    """
    from scripts import check_override_locks

    overrides = tmp_path / "p-overrides.txt"
    lock = tmp_path / "p-requirements.txt"
    overrides.write_text("aiohttp==3.14.3\n", encoding="utf-8")
    lock.write_text("# uv pip compile --overrides somewhere-else.txt\naiohttp==3.14.3\n",
                    encoding="utf-8")
    monkeypatch.setattr(check_override_locks, "ROOT", tmp_path)
    monkeypatch.setattr(check_override_locks, "PAIRS", [(overrides, lock)])

    assert check_override_locks.main() == 1
    assert "asserted rather than observed" in capsys.readouterr().out


def test_an_empty_override_file_is_a_failure_not_a_vacuous_pass(
    tmp_path, monkeypatch, capsys
) -> None:
    """Zero pins must not read as zero violations.

    An override file that has been emptied is either a mistake or a remedy someone deleted, and
    a gate that reports PASS over nothing is the shape this repository has been bitten by often
    enough to test for by reflex.
    """
    from scripts import check_override_locks

    overrides = tmp_path / "e-overrides.txt"
    lock = tmp_path / "e-requirements.txt"
    overrides.write_text("# all remedies adopted upstream\n", encoding="utf-8")
    lock.write_text(f"# uv pip compile --overrides {overrides} -o {lock}\n", encoding="utf-8")
    monkeypatch.setattr(check_override_locks, "ROOT", tmp_path)
    monkeypatch.setattr(check_override_locks, "PAIRS", [(overrides, lock)])

    assert check_override_locks.main() == 1
    assert "declares no pins" in capsys.readouterr().out
