"""SEC-75: a high-control mutation must never look like it simply succeeded.

This test used to read ui/src/panels. That frontend was retired on 2026-08-11
and the file it opened first (studio/skillsStudio/SkillUpsertForm.tsx) went with
it, so the test failed on a missing path rather than on a broken guarantee.

The guarantee did not lapse with its subject. The Worker is now the only surface
that issues these mutations, so it inherits the invariant, and the shape of the
check is translated rather than copied:

  - the old UI proved governance by rendering a PendingHumanCard and naming the
    control verb (control.skill.upsert and friends) in the same panel.
  - the Worker does not carry those verb literals at all. It proves the same
    thing three ways - reading `pending_human` off the receipt, holding an
    `hitl_request_id`, or driving the shared `useExactApprovalFinalizer`. Those
    are the same three signals tests/worker_feature_ledger.py classifies a
    governed control source by, so the two readers agree on what "governed"
    means rather than each inventing it.

Copying the old assertions verbatim would have been fiction: it would have
asserted strings the Worker has no reason to contain, and passed only because
it was looking in the wrong place.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.worker_surface_ledger import RETIRED_WORKER_ROUTES

ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / "apps" / "worker" / "src"

# Every SDK method whose kernel route can answer with a pending-human receipt
# instead of a completed mutation.
HIGH_CONTROL_MUTATIONS = (
    "upsertSkill",
    "upsertNoun",
    "upsertVerb",
    "setBinding",
    "activateAdapter",
    "deactivateAdapter",
    "deleteAdapter",
    "scheduleWorkflow",
    "triggerWorkflow",
    "patchUser",
)

GOVERNED_SIGNALS = ("pending_human", "hitl_request_id", "useExactApprovalFinalizer")


def _callsites(method: str) -> list[Path]:
    return [
        path
        for path in WORKER.rglob("*.tsx")
        if f"client.{method}(" in path.read_text(encoding="utf-8")
    ]


@pytest.mark.invariant("SEC-75")
def test_high_control_mutations_render_the_pending_human_contract() -> None:
    # A wholesale-moved Worker tree would make every loop below vacuous, so the
    # scan is proven non-empty before anything is concluded from it.
    scanned = list(WORKER.rglob("*.tsx"))
    assert len(scanned) >= 40, (
        f"scanned nothing meaningful: {WORKER} yielded {len(scanned)} components, "
        "so the checks below would pass over an empty tree"
    )

    # A high-control mutation with no callsite is acceptable ONLY when the
    # register says its surface was retired. That keeps the original meaning of
    # this gate - a mutation must not become unreachable by accident - while
    # admitting the ones that became unreachable ON PURPOSE, on the record.
    retired_methods = {
        surface.sdk_method for surface in RETIRED_WORKER_ROUTES.values()
    }
    unrouted: list[str] = []
    for method in HIGH_CONTROL_MUTATIONS:
        callsites = _callsites(method)
        if not callsites:
            assert method in retired_methods, (
                f"no Worker component calls client.{method} - either the mutation "
                "moved and this list is stale, or the surface was dropped and the "
                "capability is now unreachable with nothing recording it"
            )
            continue
        for path in callsites:
            source = path.read_text(encoding="utf-8")
            if not any(signal in source for signal in GOVERNED_SIGNALS):
                unrouted.append(f"{path.relative_to(WORKER).as_posix()} -> {method}")

    assert not unrouted, (
        "high-control mutations issued without a governed path; each of these "
        "would report a queued change as a made one: " + ", ".join(sorted(unrouted))
    )
