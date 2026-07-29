"""A refusal must say what would have been accepted - to the CALLER, never to the ledger.

Two audiences, two provenances, one validation failure.

THE LEDGER asks "what happened", and its answer must be value-free: it is
append-only and hash-chained, so a field written wrongly there can never be
unwritten ([2026] VJS-CC-BOLTRIG-SCHEMA-VALIDATION-LEDGER-001). That half is
unchanged by this module and is asserted here to STAY unchanged.

THE CALLER asks a different question - "what should I have sent" - and used to
receive `{"status":"error","reason":"schema_invalid"}` and nothing else. Not the
field, not the expected shape. Observed on Classical Visas 2026-07-29: a model
sent `entities` as a string where the schema wants an array, and retried the
identical wrong call FOUR times, because the answer was the same opaque word
each time. Four of its five tool calls failed that way. A control that refuses
without saying what would pass does not teach, it just repeats.

The order itself prescribes this disposal for everything outside the ledger's
narrow admission rule: "derived at read time from the system of record, pinned
by a digest". A live response is not a store, the schema is in hand at the
moment of failure, and the digest already says which schema.

The line held throughout: the SCHEMA's expectation may travel back (a type name,
an enum roster); the offending INSTANCE never does, in either direction.
"""

from __future__ import annotations

import pytest

from boltrig.kernel.dispatch import _reject_if_invalid
from boltrig.models import SchemaValidationError

SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "limit": {"type": "integer", "maximum": 50},
        "entities": {
            "type": "array",
            "items": {"type": "string", "enum": ["matters", "documents", "all"]},
        },
    },
    "required": ["query"],
}


def _fail(instance: dict) -> SchemaValidationError:
    with pytest.raises(SchemaValidationError) as exc:
        _reject_if_invalid("input", "opbox.search", SEARCH_SCHEMA, instance)
    return exc.value


# --- the caller can now correct itself -------------------------------------


def test_the_exact_live_failure_now_names_the_field_and_the_shape() -> None:
    """The Classical Visas call, verbatim: entities as a string, not an array."""
    detail = _fail({"query": "Rendall", "entities": "matters"}).caller_detail()
    hints = detail["schema_hints"]
    assert len(hints) == 1
    assert hints[0]["field"] == "entities"
    assert hints[0]["keyword"] == "type"
    assert hints[0]["expected"] == "array"


def test_an_enum_violation_returns_the_allowed_roster() -> None:
    """Knowing it must be an array is no help if the members are also wrong."""
    hints = _fail({"query": "x", "entities": ["matters", "nonsense"]}).caller_detail()["schema_hints"]
    assert any(set(h.get("expected") or []) >= {"matters", "documents", "all"} for h in hints)


def test_a_missing_required_field_says_which() -> None:
    hints = _fail({"entities": ["all"]}).caller_detail()["schema_hints"]
    assert any(h["keyword"] == "required" for h in hints)


def test_the_digest_pins_which_schema_the_hint_came_from() -> None:
    """Without it a caller cannot tell a stale schema from a wrong call - the
    exact confusion behind the get_matter defect, where the door published one
    shape and the kernel enforced another."""
    assert _fail({"entities": "x"}).caller_detail()["schema_digest"]


# --- and the ledger is untouched -------------------------------------------


def test_hints_never_enter_the_audit_row() -> None:
    """THE LOAD-BEARING ONE. `expected` carries schema VALUES, which the order
    forbids in an append-only store. If this ever fails, the cure has quietly
    become the defect it was built beside."""
    err = _fail({"query": "x", "entities": "matters"})
    audited = err.audit_detail()
    assert "schema_hints" not in audited
    assert "expected" not in str(audited)
    # the audited half is exactly what it always was
    assert set(audited["schema_errors"][0]) == {"schema_path", "keyword"}


@pytest.mark.parametrize(
    "secret_instance",
    [
        {"query": "sk-live-DEADBEEF-not-a-real-key", "entities": "matters"},
        {"query": "x", "entities": "sk-live-DEADBEEF-not-a-real-key"},
        {"query": "x", "limit": 999999},
    ],
)
def test_the_offending_instance_never_travels_in_either_direction(secret_instance) -> None:
    """A schema failure is the one place a caller's raw input is in hand and a
    naive message would embed it verbatim. That must not reach the ledger (it
    cannot be unwritten) and must not reach the response either (it may be
    logged by whoever receives it)."""
    err = _fail(secret_instance)
    blob = str(err.audit_detail()) + str(err.caller_detail())
    assert "DEADBEEF" not in blob
    assert "999999" not in blob


def test_a_const_expectation_is_withheld() -> None:
    """`const`'s schema value IS the literal expected instance, so it is a value
    in every sense and is deliberately absent from the safe-keyword roster -
    the same cut the order drew when it refused validator_value wholesale."""
    schema = {"type": "object", "properties": {"mode": {"const": "s3cret-mode"}}}
    with pytest.raises(SchemaValidationError) as exc:
        _reject_if_invalid("input", "v", schema, {"mode": "wrong"})
    assert "s3cret-mode" not in str(exc.value.caller_detail())
