"""The IaC misconfiguration gate is pinned, offline, blocking and CI-enforced (IAC-003).

This file exists because of how nearly the invariant died. Its single test lived in
``tests/deploy/test_pi_dependency_lock.py``, a file named for the Pi sidecar's
dependency graph, and it has nothing to do with Pi: it asserts the Trivy digest pin,
the offline flags, the blocking severity, that CI actually runs the target, and that
every ``.trivyignore.yaml`` exception is path-scoped, justified and expiring.

Retiring the Pi lane deleted that file. IAC-003 had exactly one binding, so the
deletion would have taken the whole invariant with it, and the only reason it did not
is that ``scripts/check_invariants.py`` reports a claimed test with no backing marker
as catalogue drift and fails. That gate is the difference between a subject being
retired and a property being lost, and it earned its keep here.

The lesson is in the filing, not the code: a test's home should be the property it
proves, never the ticket that happened to introduce it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]


def _text(path: str) -> str:
    return (_REPO / path).read_text()


@pytest.mark.security
@pytest.mark.invariant("IAC-003")
def test_iac_scan_is_pinned_offline_blocking_and_ci_enforced() -> None:
    makefile = _text("Makefile")
    workflow = _text(".github/workflows/security.yml")
    ignore = yaml.safe_load(_text(".trivyignore.yaml"))

    assert "aquasec/trivy:0.72.0@sha256:" in makefile
    assert "--skip-check-update --skip-version-check" in makefile
    assert "--severity HIGH,CRITICAL --exit-code 1" in makefile
    assert "make python-audit sast iac-scan PY=python" in workflow
    exceptions = ignore["misconfigurations"]
    assert exceptions
    assert all(item.get("paths") and item.get("expired_at") and item.get("statement") for item in exceptions)
    # 2026-VJS-CC-BOLTRIG-SUPPLY-CHAIN-ADVISORY-ACCEPTANCE-001 D1: a vulnerability
    # acceptance is scoped to the operative path - an entry with no paths (a
    # global ignore) or no expiry fails here, so CVE-2026-56852 can never be
    # silenced where x/text is reachable in another artefact.
    vulnerabilities = ignore["vulnerabilities"]
    assert vulnerabilities
    assert all(item.get("paths") and item.get("expired_at") and item.get("statement") for item in vulnerabilities)
