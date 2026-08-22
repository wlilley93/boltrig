"""Every side-effecting builtin verb that touches an external system is HIGH.

`[2026] VJS-APPEAL 1` affirmed that LOW verbs run with no synchronous human veto
BY DESIGN, and LJ-2's obiter named the one residual risk: a genuinely
effect-bearing verb left at LOW, so no human is ever asked before it acts. The
calibration audit (`scripts/calibration-audit.py`) found exactly that -
ms_graph's `document.create` / `document.update` write into a customer's drive
while every other write in the SAME adapter was explicitly HIGH.

This pins the class, not just the two verbs: for the credentialed builtin
adapters (the ones that reach a real external system), a verb whose ACTION
segment is a write must declare `consequence="high"`. The in-memory demo
adapter is deliberately excluded and justified below - it has no external
effect at all, so LOW is the correct calibration there, not an oversight.
"""

from __future__ import annotations

import pytest

from boltrig.adapters.builtin.jira import build as build_jira
from boltrig.adapters.builtin.ms_graph import build as build_ms_graph

# Write ACTIONS (the last dotted segment), matching the calibration audit's
# rule: the action is what has the effect, so `charge.list` is a read while
# `document.create` is a write.
_WRITE_ACTIONS = frozenset(
    {
        "create", "update", "delete", "remove", "send", "post", "put", "patch",
        "upsert", "insert", "write", "publish", "comment", "create_event",
        "delete_event",
    }
)


def _write_verbs(adapter) -> list:
    return [
        spec
        for spec in adapter.describe()
        if spec.verb_id.rsplit(".", 1)[-1] in _WRITE_ACTIONS
    ]


@pytest.mark.parametrize(
    ("name", "build"),
    [("ms_graph", build_ms_graph), ("jira", build_jira)],
)
def test_every_external_write_declares_a_high_consequence(name, build) -> None:
    adapter = build()
    writes = _write_verbs(adapter)
    assert writes, f"{name} declares no write verbs - the guard would be vacuous"
    low = sorted(s.verb_id for s in writes if s.consequence != "high")
    assert low == [], (
        f"{name}: these write verbs reach a real external system but sit below "
        f"HIGH, so no human is ever asked before they act: {low}. Fix as DATA - "
        f'set consequence="high" on the VerbSpec.'
    )


def test_the_in_memory_demo_adapter_is_deliberately_low() -> None:
    """Not an oversight: memory_tickets writes to an in-process dict, needs no
    credential and no network, so there is no external effect for a human to
    veto. It documents the OTHER side of the calibration - LOW is a decision
    here, which is why the guard above is scoped to the credentialed adapters."""
    from boltrig.adapters.builtin.memory_tickets import build as build_tickets

    specs = {s.verb_id: s for s in build_tickets().describe()}
    assert specs["ticket.create"].consequence == "low"
