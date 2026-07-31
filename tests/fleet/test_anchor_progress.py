"""The anchor janitor must distinguish "nothing to seal" from "cannot see the fleet".

On 2026-07-31 this loop ran for nine hours anchoring nothing. RLS had made its
tenant enumeration return an empty list, so the per-tenant body never executed:
no anchors, no receipts, no log output, no errors, and a return value of 0 that is
also the correct answer for a quiet deployment. The audit chain quietly stopped
being sealed and the only way to find out was to go and look at it.

``sealed`` is therefore not a judgeable number on its own. These tests pin the
three that are.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import pytest

from boltrig.fleet.anchor import AnchorSweepOutcome, run_anchor_sweep_detailed
from boltrig.fleet.sweep_progress import STALL_CYCLES


@dataclass
class _Org:
    id: str


class _Store:
    def __init__(self, orgs):
        self._orgs = orgs

    async def list_orgs(self):
        return list(self._orgs)


class _Anchorer:
    """Seals whichever tenants are named; raises for those in ``fail``."""

    def __init__(self, seal=(), fail=()):
        self._seal = set(seal)
        self._fail = set(fail)

    async def anchor(self, tenant_id, workspace_id=None):
        if tenant_id in self._fail:
            raise RuntimeError("anchor exploded")
        if tenant_id in self._seal:
            return type("A", (), {"seq_start": 1, "seq_end": 2, "is_dev_fallback": False})()
        return None  # nothing new to seal: a legitimate no-op


def test_a_quiet_sweep_and_a_blind_one_report_different_numbers():
    """The distinction the old int return could not express.

    Both produce sealed=0. Only ``tenants`` separates them.
    """
    quiet = asyncio.run(run_anchor_sweep_detailed(_Store([_Org("a")]), _Anchorer()))
    blind = asyncio.run(run_anchor_sweep_detailed(_Store([]), _Anchorer()))

    assert quiet.sealed == blind.sealed == 0, "both look identical by anchors written"
    assert quiet.tenants == 1 and quiet.handled == 1
    assert blind.tenants == 0 and blind.handled == 0


def test_a_failing_tenant_is_counted_not_merely_logged():
    outcome = asyncio.run(
        run_anchor_sweep_detailed(
            _Store([_Org("a"), _Org("b"), _Org("c")]),
            _Anchorer(seal=["a"], fail=["b"]),
        )
    )
    assert outcome == AnchorSweepOutcome(tenants=3, sealed=1, failed=1)
    assert outcome.handled == 2, "a no-op tenant was still evaluated successfully"


def test_zero_tenants_is_reported_at_WARNING_and_names_the_cause(caplog):
    """The exact failure, and it must not whisper.

    seen=0/acted=0 is idle by definition, so SweepProgress cannot catch this - it
    documents that blind spot. The loop must call it out itself.
    """
    from boltrig.fleet.anchor import _report
    from boltrig.fleet.sweep_progress import SweepProgress

    with caplog.at_level(logging.INFO, logger="boltrig.fleet.anchor"):
        _report(SweepProgress("audit-anchor"), AnchorSweepOutcome(0, 0, 0))

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "zero tenants must not be logged as an ordinary idle cycle"
    message = warnings[0].getMessage()
    assert "ZERO tenants" in message
    assert "RLS" in message, (
        "the message must name the cause that actually produced this, or the next "
        "person reads it as an empty deployment"
    )


def test_every_tenant_failing_escalates_to_stalled(caplog):
    """seen>0 with acted=0, repeated, is the shape SweepProgress exists to catch."""
    from boltrig.fleet.anchor import _report
    from boltrig.fleet.sweep_progress import SweepProgress

    progress = SweepProgress("audit-anchor")
    with caplog.at_level(logging.INFO, logger="boltrig.fleet.sweep_progress"):
        for _ in range(STALL_CYCLES):
            _report(progress, AnchorSweepOutcome(tenants=2, sealed=0, failed=2))

    assert progress.consecutive_stalled >= STALL_CYCLES
    assert any("STALLED" in r.getMessage() for r in caplog.records)


def test_a_quiet_deployment_is_not_slandered_as_stalled():
    """A tenant with no new audit rows is a clean no-op, forever, and that is fine.

    If a no-op counted as "saw work and did none" this janitor would cry wolf
    daily on every idle deployment, and a check that cries wolf gets ignored.
    """
    from boltrig.fleet.anchor import _report
    from boltrig.fleet.sweep_progress import SweepProgress

    progress = SweepProgress("audit-anchor")
    for _ in range(STALL_CYCLES + 3):
        _report(progress, AnchorSweepOutcome(tenants=1, sealed=0, failed=0))
    assert progress.consecutive_stalled == 0


@pytest.mark.parametrize("tenants,failed,expected", [(3, 0, 3), (3, 3, 0), (0, 0, 0)])
def test_handled_is_tenants_minus_failures(tenants, failed, expected):
    assert AnchorSweepOutcome(tenants, 0, failed).handled == expected
