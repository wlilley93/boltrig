"""Every "pin invariants" court directive, held to the catalogue that pins them.

Several orders end with a directive of the same shape: pin THESE behaviours as
declared invariants and keep binding debt at zero. Nothing checked the first half.

The gap is precise, and it is not covered by the invariant gate. That gate proves
two things - every DECLARED invariant is bound to a test, and every MARKER is
declared - and both hold while a declaration and its marker are deleted together.
Remove `SEC-128:` from the catalogue and the `@pytest.mark.invariant("SEC-128")`
that names it, and every existing check stays green while a court directive
quietly stops being pinned. That is the exact failure this repository already
suffered once, when the catalogue ate a whole invariant to a duplicate id and
every gate went on passing.

So this asserts the other half: the invariant ids each directive ordered pinned
are DECLARED. It deliberately does not re-assert that they are bound - that is
check_invariants.py's job, and duplicating it here would make this file look
stronger than it is.

The table is written by hand and that is the honest cost of it. It cannot be
derived: a directive names behaviours in prose ("overcap rejected, nothing
persisted"), not invariant ids, and the mapping between them is a reading of the
order. Deriving it from the markers in each order's test files was tried and is
VACUOUS - a marker must already be declared, so the assertion could never fail.
"""

from __future__ import annotations

import pathlib
import re

import pytest

pytestmark = pytest.mark.security

CATALOGUE = pathlib.Path(__file__).resolve().parents[1] / "invariants.yaml"

# (citation, directive) -> the invariant ids that directive ordered pinned.
PINS: dict[tuple[str, str], tuple[str, ...]] = {
    # [2026] VJS-COUNTY 3 D5: over-cap rejected with nothing persisted, the
    # manifest cannot loosen the code default, the envelope is enforced, and a
    # non-text attachment never reaches the task.
    ("[2026] VJS-COUNTY 3", "D5"): ("SEC-79", "SEC-80"),
    # [2026] VJS-COUNTY 4 D8: immutability, continuity exclusion with prefix
    # stability, fail-closed RBAC, last-message-only, audit row on supersede.
    ("[2026] VJS-COUNTY 4", "D8"): ("SEC-25", "SEC-81", "SEC-82", "SEC-83"),
    # [2026] VJS-COUNTY 5 D1: self-improvement raises competence, never
    # authority - the grant ceiling, memory.improve, and provenance.
    ("[2026] VJS-COUNTY 5", "D1"): ("SEC-84",),
    # [2026] VJS-COUNTY 6 D6: cancel is owner-only and fail-closed, takes effect
    # only at a cooperative point, and CANCELLED is terminal and durable.
    ("[2026] VJS-COUNTY 6", "D6"): ("SEC-85", "SEC-86", "SEC-87"),
    # [2026] VJS-COUNTY 8 D8: no cross-org or cross-workspace read, switching
    # re-authorized via membership, AI keys sealed, scoped reads via membership.
    ("[2026] VJS-COUNTY 8", "D8"): (
        "SEC-103", "SEC-104", "SEC-105", "SEC-106", "SEC-107",
        "SEC-112", "SEC-113", "SEC-115", "SEC-117", "SEC-118", "SEC-119",
    ),
    # [2026] VJS-COUNTY 11 D6: one active tenant per request, the switch is the
    # only way to change it, no cross-org read, provisioning yields a usable login.
    ("[2026] VJS-COUNTY 11", "D6"): ("SEC-131", "SEC-132", "SEC-133", "SEC-134"),
    # [2026] VJS-COUNTY 12 D6: requestUserInput never terminates the pump, the
    # answer predicate is the shared 406 function, HIGH is never timer-approved,
    # and a missing or ambiguous approve label fails closed.
    ("[2026] VJS-COUNTY 12", "D6"): (
        "CODEX-APPROVAL-1", "CODEX-APPROVAL-2", "CODEX-APPROVAL-3", "CODEX-APPROVAL-4",
    ),
}


def _declared() -> set[str]:
    """Every invariant id the catalogue declares, at its own indent level."""
    text = CATALOGUE.read_text(encoding="utf-8")
    return set(re.findall(r"^  ([A-Z][\w-]*):$", text, re.MULTILINE))


@pytest.mark.parametrize(("where", "invariants"), sorted(PINS.items()))
def test_a_pin_invariants_directive_still_has_its_invariants(
    where: tuple[str, str], invariants: tuple[str, ...]
) -> None:
    citation, directive = where
    declared = _declared()
    assert declared, "scanned nothing: the catalogue declared no invariants at all"
    missing = [inv for inv in invariants if inv not in declared]
    assert not missing, (
        f"{citation} {directive} ordered these pinned as invariants and they are no "
        f"longer declared in tests/invariants.yaml: {missing}. Either restore them "
        "or go back to the court - a directive cannot be unpinned by an edit."
    )


# [2026] VJS-CC-BOLTRIG-RATE-LIMIT-WINDOW-001 D8 is a different shape and gets its own check: it does not
# name behaviours, it orders one specific TEST to stay bound, "so a move to a
# sliding window breaks a mechanical check, not a comment".
_BURST_TEST = pathlib.Path(__file__).with_name("test_two_factor.py")


def test_the_boundary_burst_test_is_still_bound_to_a_declared_invariant() -> None:
    """[2026] VJS-CC-BOLTRIG-RATE-LIMIT-WINDOW-001 D8.

    The limiter's window is a fixed calendar minute, so an attacker timing
    attempts across a bucket boundary gets 2x the configured maximum. The court
    accepted that bound on the condition that the test proving it stays bound to
    a declared invariant - because the alternative, a comment, is what the whole
    of this programme exists to stop relying on.
    """
    source = _BURST_TEST.read_text(encoding="utf-8")
    match = re.search(
        r'@pytest\.mark\.invariant\("([^"]+)"\)\s*\n'
        r"(?:@[^\n]*\n)*"
        r"def test_the_window_is_fixed_not_sliding\b",
        source,
    )
    assert match, (
        "the boundary-burst test is gone or no longer carries an invariant marker "
        f"in {_BURST_TEST.name}: RATE-LIMIT-WINDOW-001 D8 required it to stay bound"
    )
    assert match.group(1) in _declared(), (
        f"the boundary-burst test is marked {match.group(1)}, which the catalogue "
        "does not declare"
    )
