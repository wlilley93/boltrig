"""Bind the Worker structural ratchet to the repository's required CI path.

The seeded TypeScript-AST behaviour tests run in ``make worker-structure`` after
the frozen Worker install. This Python bridge is deliberately dependency-free:
``python-quality`` can prove that neither Make nor CI can route around that
Worker gate without requiring a second JavaScript install in the Python job.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = ROOT / "Makefile"
WORKER_PACKAGE = ROOT / "apps" / "worker" / "package.json"
WORKER_GATE = ROOT / "apps" / "worker" / "scripts" / "check-structure.mjs"
WORKER_GATE_TESTS = ROOT / "apps" / "worker" / "scripts" / "check-structure.node.mjs"
WORKER_DEBT = ROOT / "docs" / "refactoring" / "worker-structural-debt.json"
CI = ROOT / ".github" / "workflows" / "ci.yml"


@pytest.mark.invariant("NFR-MNT-07")
def test_worker_structure_ratchet_is_required_by_worker_quality_and_ci() -> None:
    """The real Worker gate, its seeded failures, and its CI route are inseparable."""
    package = json.loads(WORKER_PACKAGE.read_text(encoding="utf-8"))
    scripts = package["scripts"]
    assert scripts["structure"] == "node scripts/check-structure.mjs"
    assert scripts["test:structure"] == "node --test scripts/check-structure.node.mjs"
    assert WORKER_GATE.is_file()
    assert WORKER_GATE_TESTS.is_file()
    assert WORKER_DEBT.is_file()

    makefile = MAKEFILE.read_text(encoding="utf-8")
    assert "worker-structure: worker-install" in makefile
    assert "$(PNPM) run test:structure" in makefile
    assert "$(PNPM) run structure" in makefile
    assert "worker-quality: worker-structure" in makefile
    ci = CI.read_text(encoding="utf-8")
    assert "run: make worker-quality" in ci
    assert "WORKER_STRUCTURE_BASE_REF: ${{ github.event.pull_request.base.sha || github.event.before }}" in ci
    worker_job = ci.split("  worker-build:", 1)[1].split("\n  worker-desktop-package:", 1)[0]
    assert "fetch-depth: 0" in worker_job, "the event base commit must exist in the CI checkout"


@pytest.mark.invariant("NFR-MNT-07")
def test_worker_structure_debt_is_owned_reasoned_expiring_and_exactly_shaped() -> None:
    """Even Python-only validation refuses an eternal or weakly-shaped waiver."""
    document = json.loads(WORKER_DEBT.read_text(encoding="utf-8"))
    assert set(document) == {"version", "limits", "exemptions"}
    assert document["version"] == 1
    assert document["limits"] == {
        "max_file_lines": 400,
        "max_function_lines": 80,
        "max_parameters": 5,
        "max_complexity": 15,
        "max_nesting_depth": 4,
    }
    expected_fields = {
        "file_lines",
        "max_function_lines",
        "max_parameters",
        "max_complexity",
        "max_nesting_depth",
        "over_limit_functions",
        "owner",
        "reason",
        "expires",
    }
    today = date.today()
    assert document["exemptions"], "the initial legacy debt census must not vanish silently"
    for path, exemption in document["exemptions"].items():
        assert path.startswith("apps/worker/src/") and path.endswith((".ts", ".tsx"))
        assert set(exemption) == expected_fields
        assert exemption["owner"].strip() == exemption["owner"]
        assert exemption["reason"].strip() == exemption["reason"]
        assert exemption["owner"] and exemption["reason"]
        assert date.fromisoformat(exemption["expires"]) >= today
        # An exemption must EXEMPT something, and an over-limit function is
        # only one of the five ways to need one.
        #
        # This used to demand a named over-limit function, which made the
        # ratchet unlowerable at its last step: when FamiliarWebGLRenderer's
        # frame() was extracted to familiarDrive.ts the file went from one
        # over-limit function to none, and correctly lowering the entry to
        # an empty list failed this assertion. The file is still 435 lines
        # against a 400 limit, so the exemption is still owed -- it is owed
        # for its SIZE now rather than for a function, and refusing that
        # state would mean either keeping a stale entry or deleting a real
        # one.
        over_limits = (
            exemption["file_lines"] > document["limits"]["max_file_lines"]
            or exemption["max_function_lines"] > document["limits"]["max_function_lines"]
            or exemption["max_parameters"] > document["limits"]["max_parameters"]
            or exemption["max_complexity"] > document["limits"]["max_complexity"]
            or exemption["max_nesting_depth"] > document["limits"]["max_nesting_depth"]
        )
        assert over_limits, (
            f"{path} exempts nothing: every measurement is inside its limit, "
            "so the entry should be deleted rather than carried"
        )
