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
import subprocess
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

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


@pytest.mark.invariant("NFR-MNT-05")
def test_health_gate_examples_are_not_mistaken_for_application_routes() -> None:
    routes = check_health_claims.routes_in(REPO_ROOT)
    assert Path(__file__).resolve() not in routes
    assert Path(check_health_claims.__file__).resolve() not in routes


@pytest.mark.invariant("NFR-MNT-05")
def test_health_gate_parses_python_module_entrypoints() -> None:
    services = check_health_claims.parse_services(REPO_ROOT / "docker-compose.yml")
    assert services["fleet-worker"]["command"] == "python -m boltrig.api.worker"
    assert services["browser-executor"]["command"] == "python -m boltrig.fleet.browser_executor"
    assert services["hatchet-worker"]["command"] == "python -m boltrig.fleet.hatchet_worker"


@pytest.mark.invariant("NFR-MNT-05")
def test_health_gate_accepts_only_the_executor_own_live_unix_socket_probe() -> None:
    probe = "CMD-SHELL python -m boltrig.fleet.browser_executor --health"
    command = "python -m boltrig.fleet.browser_executor"

    assert check_health_claims.consults_private_socket_readiness(probe, command)[0] is True
    assert check_health_claims.consults_private_socket_readiness(
        probe, "python -m boltrig.api.worker"
    )[0] is False
    assert check_health_claims.consults_private_socket_readiness(
        "python -m boltrig.fleet.browser_executor", command
    )[0] is False


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
def test_source_gates_include_new_nonignored_files_before_staging(
    tmp_path, monkeypatch
) -> None:
    """A new module is part of the change even before Git's index knows it."""
    from scripts import build_claim_inventory, check_reachability

    source = tmp_path / "boltrig" / "new_contract.py"
    source.parent.mkdir()
    source.write_text("def new_contract():\n    return True\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(args, *, capture_output, check, text):
        assert capture_output and check and text
        calls.append(args)
        return SimpleNamespace(stdout="boltrig/new_contract.py\0")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(build_claim_inventory, "ROOT", tmp_path)
    monkeypatch.setattr(check_reachability, "ROOT", tmp_path)

    assert build_claim_inventory.tracked("boltrig/**/*.py") == [source]
    assert check_reachability._sources() == [source]
    for args in calls:
        assert "--cached" in args
        assert "--others" in args
        assert "--exclude-standard" in args


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

    good = {"owner": "x-maintainers", "expires": "2099-12-31", "reason": "a real one",
            "blocker": "caller:boltrig/kernel/dispatch.py:1"}
    allow, problems = check_unwired_claims.load_allow(_write(good))
    assert problems == [] and allow == {"thing": "a real one"}

    for missing, word in (
        ({**good, "owner": " "}, "owner"),
        ({**good, "reason": ""}, "reason"),
        ({k: v for k, v in good.items() if k != "expires"}, "expiry"),
        ({**good, "expires": "2020-01-01"}, "expired"),
        # THE BLOCKER, added by the workflow-promotion order's D6. A waiver says "not yet";
        # this makes it say what it is waiting FOR, in a form a reader can check. The waiver
        # that prompted it said it awaited "the product decision of WHEN promotion runs", and
        # the court found there was no such decision and that the real blocker was a different
        # question nobody had asked. Prose can be sincere and still name the wrong thing for
        # three months.
        ({k: v for k, v in good.items() if k != "blocker"}, "blocker"),
        ({**good, "blocker": "soon"}, "blocker"),
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


# --- Tier 0: the claim inventory, and the ratchet that is the goal's only criterion ---------
#
# The fourth gate, added 2026-07-27, and the defect it exists for is the largest of the four:
# GOAL-claims-must-be-load-bearing.md called the inventory "the piece nobody has done and
# everything else depends on it", then described "the inventory's UNVERIFIED column" as partly
# worked, and there was no inventory and never had been. A document about claims being
# load-bearing carrying a false claim about its own foundation.


@pytest.mark.invariant("NFR-MNT-03")
def test_the_committed_inventory_is_current_and_the_residue_has_not_grown(capsys) -> None:
    """The real tree, both halves: byte-identical regeneration and the pinned residue."""
    from scripts import check_claim_inventory

    assert check_claim_inventory.main() == 0, capsys.readouterr().out


def test_a_stale_inventory_is_a_failure_not_a_pass(tmp_path, monkeypatch, capsys) -> None:
    """A census nobody re-derives is a snapshot.

    This is the assertion that stops the artefact rotting into decoration: edit the committed
    TSV, or let the sources move past it, and the gate goes red rather than reading back the
    file's own contents and agreeing with them.
    """
    from scripts import build_claim_inventory, check_claim_inventory

    stale = tmp_path / "claim-inventory.tsv"
    stale.write_text("weight\tclassification\tsource\tlocation\tsubject\tclaim\n", encoding="utf-8")
    monkeypatch.setattr(build_claim_inventory, "OUT", stale)
    monkeypatch.setattr(check_claim_inventory, "OUT", stale)

    assert check_claim_inventory.main() == 1
    assert "STALE" in capsys.readouterr().out


def test_a_residue_above_the_baseline_is_refused(tmp_path, monkeypatch, capsys) -> None:
    """"The number of unbound load-bearing claims may only decrease" is the goal's own and
    only success criterion, and until this gate existed nothing measured it.

    Seeded by pinning the baseline BELOW the true count, which is the same arithmetic as a new
    claim arriving with no named mechanism.
    """
    from scripts import check_claim_inventory

    low = tmp_path / "baseline.json"
    low.write_text(json.dumps({"load_bearing_no_subject": 0}), encoding="utf-8")
    monkeypatch.setattr(check_claim_inventory, "BASELINE", low)

    assert check_claim_inventory.main() == 1
    assert "the residue GREW" in capsys.readouterr().out


def test_an_unpinned_baseline_is_a_failure_rather_than_an_unratcheted_pass(
    tmp_path, monkeypatch, capsys
) -> None:
    """A missing baseline must not read as "nothing to compare against, therefore fine".

    That is the fail-open shape this repository has now been bitten by often enough to test for
    by reflex: a check that cannot look reporting agreement it did not observe.
    """
    from scripts import check_claim_inventory

    monkeypatch.setattr(check_claim_inventory, "BASELINE", tmp_path / "does-not-exist.json")

    assert check_claim_inventory.main() == 1
    assert "no baseline pinned" in capsys.readouterr().out
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


# --- reachability is transitive ------------------------------------------------------------
#
# [2026] VJS-CC-BOLTRIG-WORKFLOW-PROMOTION-TRIGGER-001 D2. `check_unwired_claims.py` asks whether
# a name appears outside its own definition. `WorkflowLibrary.match` did, so it passed, and its
# only caller had no caller: an entire retrieval path, a learning leg and a promotion subsystem
# sat behind one hop of apparent wiring, and a court was told the reader ran on every selection.


def test_nothing_is_newly_unreachable_from_every_root(capsys) -> None:
    """The real tree, ratcheted."""
    from scripts import check_reachability

    assert check_reachability.main() == 0, capsys.readouterr().out


def test_a_chain_whose_head_has_no_caller_is_reported(tmp_path, monkeypatch) -> None:
    """The property the first-hop gate cannot see.

    `root -> a -> b` is reachable. `c -> d` is not, even though `c` has a caller in the sense
    that `d` names it: the chain never reaches a root. Both `c` and `d` must be reported, and
    `b` must not.
    """
    from scripts import check_reachability

    pkg = tmp_path / "boltrig"
    pkg.mkdir()
    (pkg / "m.py").write_text(
        "import functools\n"
        "\n"
        "@functools.cache\n"
        "def root():\n"
        "    return a()\n"
        "\n"
        "def a():\n"
        "    return b()\n"
        "\n"
        "def b():\n"
        "    return 1\n"
        "\n"
        "def c():\n"
        "    return d()\n"
        "\n"
        "def d():\n"
        "    return 2\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(check_reachability, "ROOT", tmp_path)
    monkeypatch.setattr(check_reachability, "_sources", lambda: [pkg / "m.py"])

    graph = check_reachability._build()
    seen: set[str] = set()
    frontier = list(graph.roots)
    while frontier:
        name = frontier.pop()
        if name in seen:
            continue
        seen.add(name)
        frontier.extend(graph.edges.get(name, ()))

    unreachable = {n for n in graph.defined if n not in seen}
    assert unreachable == {"c", "d"}, unreachable


def test_a_root_without_a_reason_is_refused(tmp_path, monkeypatch, capsys) -> None:
    """The root set is where this check can be quietly disabled, so an unreasoned root is a
    failure rather than a shortcut. Limit L1 of the order says no mechanical check can hold
    "the root set is honest"; this holds the one part of it that can be."""
    from scripts import check_reachability

    roots = tmp_path / "roots.json"
    roots.write_text(json.dumps({"roots": {"whatever": ""}, "unreachable_baseline": 9999}),
                     encoding="utf-8")
    monkeypatch.setattr(check_reachability, "ROOTS_FILE", roots)

    assert check_reachability.main() == 1
    assert "declares no reason" in capsys.readouterr().out


def test_reachability_without_a_baseline_is_a_failure_not_an_unratcheted_pass(
    tmp_path, monkeypatch, capsys
) -> None:
    """Same fail-open shape as the claim inventory's: a missing baseline must not read as
    nothing-to-compare-against."""
    from scripts import check_reachability

    monkeypatch.setattr(check_reachability, "ROOTS_FILE", tmp_path / "absent.json")

    assert check_reachability.main() == 1
    assert "no baseline pinned" in capsys.readouterr().out


# --- the workflow-promotion order's remaining directives -------------------------------------


def test_a_package_re_export_no_longer_counts_as_wiring(tmp_path, monkeypatch) -> None:
    """[2026] VJS-CC-BOLTRIG-WORKFLOW-PROMOTION-TRIGGER-001 D1.

    A single `from .m import probe_fn` in a package `__init__` used to hide a function from the
    gate entirely, and it hid three at once in `workflows/__init__.py`. A class may still be
    exported for an outside caller to CONSTRUCT, which is a real seam; a function has no such
    seam in an application package, so for functions both suppressions are dropped.
    """
    from scripts import check_unwired_claims

    pkg = tmp_path / "boltrig"
    pkg.mkdir()
    (pkg / "m.py").write_text("def probe_fn():\n    return 1\n", encoding="utf-8")
    (pkg / "__init__.py").write_text(
        'from .m import probe_fn\n\n__all__ = ["probe_fn"]\n', encoding="utf-8"
    )
    sources = [pkg / "m.py", pkg / "__init__.py"]
    src = {p: p.read_text(encoding="utf-8") for p in sources}
    *_, referenced, exported, re_exported = check_unwired_claims._collect(src)

    assert "probe_fn" not in referenced, "a re-export was counted as a reference"
    assert "probe_fn" in re_exported and "probe_fn" in exported

    (pkg / "caller.py").write_text(
        "from .m import probe_fn\n\n\ndef go():\n    return probe_fn()\n", encoding="utf-8"
    )
    src[pkg / "caller.py"] = (pkg / "caller.py").read_text(encoding="utf-8")
    *_, referenced2, _, _ = check_unwired_claims._collect(src)
    assert "probe_fn" in referenced2, "a real call site was not counted"


@pytest.mark.invariant("NFR-MNT-06")
def test_no_waiver_survives_the_deletion_of_its_subject() -> None:
    """[2026] VJS-CC-BOLTRIG-WORKFLOW-PROMOTION-TRIGGER-001 D5 and D6.

    A waiver for a symbol that no longer exists is a claim about nothing, and it is the shape
    that outlives a deletion most easily: nobody greps the waiver file when they delete a class.
    """
    from scripts import check_unwired_claims

    path = REPO_ROOT / "docs" / "refactoring" / "unwired-claims-allow.json"
    entries = json.loads(path.read_text(encoding="utf-8"))["allow"]
    source = "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in (REPO_ROOT / "boltrig").rglob("*.py")
    )
    # A waiver's SUBJECT depends on its kind. A class or function lives in the
    # Python source; a manifest knob (part 3, added 2026-07-30) lives in the
    # manifest and by definition appears in NO Python file - that absence is
    # exactly what it is waived for. Checking both against boltrig/**/*.py would
    # make every knob waiver look like a waiver for a deleted subject, so the
    # guard would fire on the correct state and teach people to loosen it.
    manifest_text = (REPO_ROOT / "manifest.example.yaml").read_text(encoding="utf-8")
    knobs = check_unwired_claims.manifest_bool_keys(manifest_text)
    for name in entries:
        if name in knobs:
            continue  # subject present in the manifest
        assert name in source, (
            f"{name} is waived but exists in neither boltrig/**/*.py nor "
            f"manifest.example.yaml"
        )

    allow, problems = check_unwired_claims.load_allow(path)
    assert problems == [], problems
    assert all(check_unwired_claims._BLOCKER.match(e["blocker"]) for e in entries.values())


def test_no_record_still_describes_the_retrieval_path_as_reachable() -> None:
    """[2026] VJS-CC-BOLTRIG-WORKFLOW-PROMOTION-TRIGGER-001 D7.

    The court was told a loop was live because code existed and had callers. The prose that said
    so must now say what is true, and this pins the specific sentences: a record may describe
    intent-based retrieval, and may not describe it as something production reaches.
    """
    generator = (REPO_ROOT / "boltrig" / "workflows" / "generator.py").read_text(encoding="utf-8")
    library = (REPO_ROOT / "boltrig" / "workflows" / "library.py").read_text(encoding="utf-8")
    pump = (REPO_ROOT / "boltrig" / "fleet" / "pump.py").read_text(encoding="utf-8")

    # Any of these phrasings will do. Pinning ONE wording would make the test a style rule and
    # would reward pasting the magic string over saying the true thing well; library.py says it
    # best of the three and would have failed a single-phrase check.
    said = ("no production caller", "no production entry point", "NOTHING WRITES IT",
            "not reachable", "has never fired")
    for name, text in (("generator.py", generator), ("library.py", library), ("pump.py", pump)):
        assert any(phrase in text for phrase in said), (
            f"{name} does not record that the retrieval or learning leg is unreached"
        )


def test_the_principal_dependency_is_a_record_with_an_id_and_an_expiry() -> None:
    """[2026] VJS-CC-BOLTRIG-WORKFLOW-PROMOTION-TRIGGER-001 D8 and D9.

    The waiver this order replaced deferred to "the product decision of WHEN promotion runs",
    which was not a decision anyone could make. A deferral has to name a record that exists, so
    that "waiting on the Principal" is checkable rather than a mood.
    """
    doc = REPO_ROOT / "docs" / "decisions" / "0019-route-by-intent-is-the-principals.md"
    assert doc.exists(), "the D8 record does not exist"
    text = doc.read_text(encoding="utf-8")
    assert "PRINCIPAL-2026-07-27-ROUTE-BY-INTENT" in text
    assert "2026-10-31" in text
    # And the ratio's consequence on expiry, so nobody reads silence as consent to keep it.
    assert "retire" in text.lower()
