"""Court directives that order the RECORD to say a particular thing.

Four orders end with a directive of this shape - not "make the system do X" but
"state the honest limit of X, where a reader will look for it". They exist because
in each case the true behaviour was surprising and the surprise was the hazard:
a rate limit that admits 2x across a boundary, a fence that makes the record
single-writer without making execution exactly-once, attachments that are inline
blobs rather than an object store.

Prose is not enforcement, which is the whole premise of this programme - and a
directive to write prose is the one case where prose IS the deliverable. That does
not make it unenforceable. What can be checked is that the sentence is still
there, in the place the court named, saying the thing it was ordered to say. An
edit that quietly drops it is exactly the drift these directives were issued
against, and until now nothing would have noticed.

These assert the LOAD-BEARING CLAUSE, not the wording. Matching a whole sentence
would turn every copy-edit into a failure and teach people to route around the
check; matching the fact - "fixed", "not sliding", "not exactly-once" - fails only
when the meaning goes.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.security

_REPO = Path(__file__).resolve().parents[2]


def _text(relative: str) -> str:
    path = _REPO / relative
    assert path.is_file(), f"scanned nothing: {relative} does not exist"
    return path.read_text(encoding="utf-8")


def test_the_ratelimit_dataclass_states_the_window_and_its_burst() -> None:
    """[2026] VJS-CC-BOLTRIG-RATE-LIMIT-WINDOW-001 D5.

    "State the fixed calendar window and its 2x burst in the RateLimit dataclass
    docstring, WHERE LIMITS ARE CONFIGURED." The place matters as much as the
    sentence: someone choosing `5/min` reads this docstring and no further, so
    this is the only spot where the note reaches the person making the mistake.
    """
    source = _text("boltrig/models/registry.py")
    body = re.search(r"class RateLimit:\s*\n\s*\"\"\"(.*?)\"\"\"", source, re.DOTALL)
    assert body, "the RateLimit dataclass has no docstring at all"
    doc = body.group(1).lower()
    for clause in ("fixed calendar window", "not per sliding", "10"):
        assert clause in doc, (
            f"the RateLimit docstring no longer states {clause!r}; COUNTY "
            "RATE-LIMIT-WINDOW-001 D5 required the fixed window and its 2x burst "
            "stated here, at the point of configuration"
        )


def test_sec_130_no_longer_asserts_a_bound_the_limiter_does_not_deliver() -> None:
    """[2026] VJS-CC-BOLTRIG-RATE-LIMIT-WINDOW-001 D6.

    The invariant used to claim a bound the fixed-window counter cannot honour.
    Amending it was the directive; this stops the amendment being reverted by
    someone tidying the description, which would restore a false claim into the
    catalogue that every other gate would go on reporting as bound and green.
    """
    catalogue = _text("tests/invariants.yaml")
    entry = re.search(r"\n  SEC-130:\n    description: (.*?)\n    tests:", catalogue, re.DOTALL)
    assert entry, "SEC-130 is gone from the catalogue or no longer has a description"
    text = entry.group(1).lower()
    assert "fixed" in text and "not a sliding" in text, (
        "SEC-130's description no longer says the window is FIXED and not sliding, "
        "so it is back to asserting a bound the limiter does not deliver"
    )


def test_the_lease_fence_records_that_it_is_not_exactly_once() -> None:
    """[2026] VJS-CC-BOLTRIG-WORK-ITEM-LEASE-FENCE-001 D9.

    The order's own honesty directive, and the reason this goal document cites it:
    the fence makes the RECORD single-writer and does NOT make execution
    exactly-once. A reader who takes the second from the first will skip
    idempotence on a step that calls the world.
    """
    source = _text("boltrig/fleet/lease_token.py").lower()
    assert "single-writer" in source, "the module no longer states what the fence DOES"
    assert "not make execution exactly-once" in source, (
        "boltrig/fleet/lease_token.py no longer records that the fence does NOT make "
        "execution exactly-once - D9's honest limit, deleted"
    )


def test_the_attachment_decision_states_the_inline_row_growth_cost() -> None:
    """[2026] VJS-COUNTY 3 D6.

    "Record in the honesty docs: inline blob in row, not an object store, with the
    row growth cost STATED." Half of that is easy to keep and half is easy to lose
    - a later editor trims the cost paragraph as negative and leaves the design
    note, which reads as an unqualified endorsement of the cheaper choice.
    """
    decision = _text("docs/decisions/0006-inline-chat-attachments.md").lower()
    assert "object store" in decision, "the decision no longer contrasts with an object store"
    assert "inline" in decision
    assert "cost" in decision and "row" in decision, (
        "the decision record no longer states the row-growth COST of storing bytes "
        "inline; COUNTY 3 D6 required the cost stated, not just the choice recorded"
    )


def test_both_unfenced_writes_dispose_of_themselves_expressly() -> None:
    """[2026] VJS-CC-BOLTRIG-WORK-ITEM-LEASE-FENCE-001 D3.

    D3's routing half - every write to a CLAIMED row goes through the fenced write
    - is proved in tests/fleet/test_lease_fence.py. This is its other half: the two
    writes deliberately left UNFENCED must dispose of themselves EXPRESSLY, and on
    the true ground.

    That wording is the point. The ruling's own opinion found the draft rationale
    false on the facts: it said requeue is out of the lane "because those rows
    carry no lease", and a parked row DOES carry a stale claim tuple, so a fence
    there would compare against a dead worker's token and usually pass. An
    exclusion recorded on a false ground is worse than no note, because the next
    reader takes it as analysis already done.
    """
    for module, subject in (
        ("boltrig/fleet/pump.py", "requeue"),
        ("boltrig/kernel/hitl_expiry.py", "_park_expired_item"),
    ):
        source = _text(module)
        assert "D3 disposal" in source, (
            f"{module} no longer records the D3 disposal for its unfenced write "
            f"({subject}); the exclusion is back to being undocumented"
        )
    pump = _text("boltrig/fleet/pump.py")
    assert 'not "there is no lease"' in pump, (
        "pump.py's D3 disposal no longer says the reason is NOT an absent lease - "
        "which is the correction the court made to its own draft, and the only part "
        "of the note that stops a reader concluding a fence would be safe here"
    )
