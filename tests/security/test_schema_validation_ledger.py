"""The schema-validation ledger order, bound.

County, First Instance, 2026-07-27, on SUBMISSION-2026-07-27-124116. Opinion at
``docs/vjs/2026-VJS-CC-BOLTRIG-SCHEMA-VALIDATION-LEDGER-001-opinion.md``.

The order refused all three pleaded options and adopted a fourth. Each test below is bound to
one of its directives, and the two that matter most are D3 and D8:

  * D3 is POSITIONAL. It does not test that a scrubber caught a secret; it tests that a secret
    used as an object KEY, and a secret used as a ``const`` in the schema, are both absent from
    the serialised audit row. The instance is never read on this path, so there is nothing to
    catch.
  * D8 proves D3 is positional and not nominal, by running the same leak test with
    ``pii.contains_secret`` monkeypatched to return None unconditionally. If D8 goes red, the
    scrubber was the thing saving the row and the defence is a pattern list.
    ([2026] VJS-CC-OPBOX 5 H1: a defence that depends on a string literal matching is not a
    trust boundary.)
"""

from __future__ import annotations

import json

import pytest

from boltrig.kernel import dispatch as dispatch_mod
from boltrig.kernel.dispatch import _summarise_params, _validate
from boltrig.kernel.schema_diagnosis import (
    MAX_PARAM_KEYS,
    MAX_SCHEMA_ERRORS,
    MAX_SCHEMA_PATH_DEPTH,
    MAX_SCHEMA_PATH_SEGMENT,
    diagnose,
    schema_digest,
)
from boltrig.models.errors import SchemaValidationError

# The verb whose live failure motivated the filing: an MCP-imported verb whose wire name is
# snake_case and whose required property is camelCase. It failed schema_invalid 8 times in 4
# seconds on a production tenant and the record could not say why.
GET_MATTER_SCHEMA = {
    "type": "object",
    "properties": {"matterId": {"type": "string"}, "limit": {"type": "integer"}},
    "required": ["matterId"],
    "additionalProperties": False,
}

# The leak fixture. Two independent vectors, in one schema on purpose:
#   * `metadata` accepts arbitrary keys, so an instance KEY becomes a segment of
#     `json_path` / `absolute_path` - which is why neither may be recorded.
#   * `token` has a `const`, so the expected LITERAL sits in `validator_value` - which is why
#     "schema-derived" is not the same as "value-free".
INSTANCE_SECRET = "sk-live-SECRETKEYFROMTHEINSTANCE"
SCHEMA_SECRET = "sk-live-EXPECTEDLITERALFROMTHESCHEMA"
LEAK_SCHEMA = {
    "type": "object",
    "properties": {
        "metadata": {"type": "object", "additionalProperties": {"type": "integer"}},
        "token": {"const": SCHEMA_SECRET},
    },
}
LEAK_PARAMS = {"metadata": {INSTANCE_SECRET: "nope"}, "token": "wrong"}


def _row(params: dict, schema: dict) -> str:
    """Everything a schema failure contributes to an audit row, serialised as it is stored."""
    errors = _validate(schema, params)
    exc = SchemaValidationError("invalid params for 'opbox.get_matter'", errors,
                                schema_digest=schema_digest(schema))
    detail = {"message": str(exc), **exc.audit_detail(), "params": _summarise_params(params)}
    return json.dumps(detail)


# --- D2: exactly {schema_path, keyword}, and keyword is allowlisted -----------------------

@pytest.mark.invariant("SEC-190")
def test_records_only_the_schema_path_and_an_allowlisted_keyword():
    """[2026] VJS-CC-BOLTRIG-SCHEMA-VALIDATION-LEDGER-001 D2.

    The pairs are the schema's own structure and nothing else."""
    # Compared as a SET. jsonschema does not promise an iteration order over sibling
    # keywords, and pinning one here would make this test fail on a library bump for a
    # reason that has nothing to do with what it guards.
    got = _validate(GET_MATTER_SCHEMA, {"matter_id": "x", "limit": "y"})
    assert {(tuple(e["schema_path"]), e["keyword"]) for e in got} == {
        (("required",), "required"),
        (("properties", "limit", "type"), "type"),
        (("additionalProperties",), "additionalProperties"),
    }


@pytest.mark.invariant("SEC-190")
def test_an_unrecognised_keyword_is_recorded_as_unknown():
    """[2026] VJS-CC-BOLTRIG-SCHEMA-VALIDATION-LEDGER-001 D2.

    `validator` comes from the schema, and an MCP-imported schema is third-party data
    (adapters/mcp_consumer.py takes it verbatim from the remote tools/list response), so a
    custom keyword could be any string. The allowlist is what stops it being copied."""

    class _Fake:
        validator = "custom_thing_from_a_remote_server"
        absolute_schema_path = ["properties", "x"]

    class _FakeValidator:
        def __init__(self, schema):
            pass

        def iter_errors(self, instance):
            yield _Fake()

    real = dispatch_mod.Draft202012Validator
    dispatch_mod.Draft202012Validator = _FakeValidator
    try:
        got = _validate({"type": "object"}, {})
    finally:
        dispatch_mod.Draft202012Validator = real
    assert got == [{"schema_path": ["properties", "x"], "keyword": "unknown"}]


# --- D3 / D8: the instance is never read, and that is positional --------------------------

@pytest.mark.invariant("SEC-190")
@pytest.mark.parametrize("nominal_defence", [True, False], ids=["scrub_live", "scrub_disabled"])
def test_no_instance_or_schema_value_reaches_the_audit_row(monkeypatch, nominal_defence):
    """[2026] VJS-CC-BOLTRIG-SCHEMA-VALIDATION-LEDGER-001 D3 and D8.

    D8 is the second parameter case.

    With ``scrub_disabled`` the write-time secret scrubber is neutered, so the ONLY thing
    keeping either secret out of the row is that neither is ever read. If this case goes red
    while ``scrub_live`` stays green, the defence is nominal and the order is breached.

    It is not hypothetical that the scrubber would miss these: ``contains_secret`` matches
    ``sk-[A-Za-z0-9]{20,}``, and the hyphens in ``sk-live-`` truncate that to four characters.
    """
    if not nominal_defence:
        from boltrig.kernel import audit as audit_mod

        monkeypatch.setattr(audit_mod.pii, "contains_secret", lambda *_a, **_k: None)

    serialised = _row(LEAK_PARAMS, LEAK_SCHEMA)
    assert INSTANCE_SECRET not in serialised, "an instance KEY reached the append-only row"
    assert SCHEMA_SECRET not in serialised, "a schema `const` literal reached the row"


@pytest.mark.invariant("SEC-190")
def test_the_forbidden_attributes_are_named_nowhere_on_the_audit_path():
    """[2026] VJS-CC-BOLTRIG-SCHEMA-VALIDATION-LEDGER-001 D3, structurally.

    The five attributes may not be referenced at all in the two modules
    that build and write an audit row, so a later edit cannot reintroduce the read by a route
    the leak fixture happens not to exercise.

    Comments are stripped first: this file's own siblings DISCUSS these names at length, and a
    rule that forbade discussing them would be a rule against explaining itself."""
    import ast
    import inspect

    from boltrig.kernel import audit as audit_mod

    # Four of the five are unique to a jsonschema ValidationError, so a module-wide ban on
    # them costs nothing and cannot be evaded by renaming a local.
    forbidden = {"json_path", "absolute_path", "instance", "validator_value"}
    # `.message` is not: `err.message` on a rate-limit error is a legitimate read in the same
    # module, and this check caught it on its first run. So `.message` is banned exactly where
    # a ValidationError can exist, which is the one function that calls `iter_errors`. A ban
    # broad enough to hit an unrelated attribute of the same name would have been turned off,
    # and a gate that gets turned off protects nothing.
    for mod in (dispatch_mod, audit_mod):
        tree = ast.parse(inspect.getsource(mod))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in forbidden:
                raise AssertionError(
                    f"{mod.__name__} reads .{node.attr}, which the schema-validation ledger "
                    "order forbids on the audit path"
                )
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            calls_iter_errors = any(
                isinstance(n, ast.Attribute) and n.attr == "iter_errors" for n in ast.walk(fn)
            )
            if not calls_iter_errors:
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Attribute) and node.attr == "message":
                    raise AssertionError(
                        f"{mod.__name__}.{fn.name} reads .message from a validation error, "
                        "which embeds the offending instance verbatim"
                    )


# --- D4: the digest, and D5: derivation at read time ---------------------------------------

def test_the_digest_is_over_the_registered_schema_and_moves_when_it_moves():
    """[2026] VJS-CC-BOLTRIG-SCHEMA-VALIDATION-LEDGER-001 D4."""
    assert schema_digest(GET_MATTER_SCHEMA) == schema_digest(dict(GET_MATTER_SCHEMA))
    mutated = {**GET_MATTER_SCHEMA, "required": ["matterId", "limit"]}
    assert schema_digest(mutated) != schema_digest(GET_MATTER_SCHEMA)


@pytest.mark.invariant("SEC-190")
def test_read_time_derivation_turns_the_live_failure_into_a_diff():
    """[2026] VJS-CC-BOLTRIG-SCHEMA-VALIDATION-LEDGER-001 D5.

    This is the whole point of the order: the row could not previously say WHICH field,
    and the guess in the case file ("perhaps the model sent matter_id") is now a measurement."""
    errors = _validate(GET_MATTER_SCHEMA, {"matter_id": "x"})
    detail = {
        "schema_errors": errors,
        "schema_digest": schema_digest(GET_MATTER_SCHEMA),
        "params": _summarise_params({"matter_id": "x"}),
    }
    got = diagnose(detail, GET_MATTER_SCHEMA)
    assert got["state"] == "diagnosed"
    assert got["missing"] == ["matterId"]
    assert got["unexpected"] == ["matter_id"]


@pytest.mark.invariant("SEC-190")
def test_a_moved_schema_declines_to_diff_rather_than_answering_from_the_wrong_one():
    """[2026] VJS-CC-BOLTRIG-SCHEMA-VALIDATION-LEDGER-001 D5, and limit L2.

    Read-time derivation is not point-in-time. The schema in force at the
    time is not retained, so the honest answer is that it moved."""
    detail = {
        "schema_errors": _validate(GET_MATTER_SCHEMA, {"matter_id": "x"}),
        "schema_digest": schema_digest(GET_MATTER_SCHEMA),
        "params": _summarise_params({"matter_id": "x"}),
    }
    got = diagnose(detail, {**GET_MATTER_SCHEMA, "required": ["matterId", "limit"]})
    assert got["state"] == "schema_moved"
    assert "missing" not in got and "unexpected" not in got


def test_a_row_written_before_the_order_says_so_rather_than_showing_an_empty_diff():
    """[2026] VJS-CC-BOLTRIG-SCHEMA-VALIDATION-LEDGER-001 D5.

    `not_recorded` and `diagnosed with nothing missing` are different facts."""
    assert diagnose({"message": "invalid params for 'x'"}, GET_MATTER_SCHEMA) == {
        "state": "not_recorded"
    }


# --- D6: the output twin -------------------------------------------------------------------

@pytest.mark.invariant("SEC-190")
def test_output_validation_records_the_same_shape_and_leaks_nothing():
    """[2026] VJS-CC-BOLTRIG-SCHEMA-VALIDATION-LEDGER-001 D6.

    The case file never mentioned output validation, and it is the worse half: the
    instance there is the ADAPTER'S RESPONSE, which is where credentials live."""
    serialised = _row({"metadata": {INSTANCE_SECRET: "nope"}, "token": "wrong"}, LEAK_SCHEMA)
    assert INSTANCE_SECRET not in serialised
    parsed = json.loads(serialised)
    assert all(set(e) == {"schema_path", "keyword"} for e in parsed["schema_errors"])


# --- D7: bounds ----------------------------------------------------------------------------

@pytest.mark.invariant("SEC-190")
def test_the_error_list_is_capped_and_says_when_it_truncated():
    """[2026] VJS-CC-BOLTRIG-SCHEMA-VALIDATION-LEDGER-001 D7.

    `truncated` is present only when findings were dropped, so its absence means the
    list is complete rather than merely short."""
    schema = {"type": "object", "properties": {f"f{i}": {"type": "integer"} for i in range(50)}}
    params = {f"f{i}": "not an integer" for i in range(50)}
    errors = _validate(schema, params)
    assert len(errors) == MAX_SCHEMA_ERRORS
    exc = SchemaValidationError("invalid", errors, schema_digest=schema_digest(schema))
    assert exc.audit_detail()["truncated"] is True
    assert "truncated" not in SchemaValidationError("invalid", errors[:2]).audit_detail()


def test_path_depth_and_segment_length_are_bounded():
    """[2026] VJS-CC-BOLTRIG-SCHEMA-VALIDATION-LEDGER-001 D7.

    A path is names, and a name is instance-influenced in length even where it is not
    instance-influenced in content."""
    deep = {"type": "object"}
    for _ in range(MAX_SCHEMA_PATH_DEPTH + 6):
        deep = {"type": "object", "properties": {"a" * 200: deep}}
    errors = _validate(deep, {"a" * 200: 1})
    for e in errors:
        assert len(e["schema_path"]) <= MAX_SCHEMA_PATH_DEPTH
        assert all(len(seg) <= MAX_SCHEMA_PATH_SEGMENT for seg in e["schema_path"])


def test_the_key_summary_is_capped_but_still_reports_the_true_count():
    """[2026] VJS-CC-BOLTRIG-SCHEMA-VALIDATION-LEDGER-001 D7, and limit L1.

    A truncated list with an honest count beats a complete list."""
    got = _summarise_params({f"k{i:03d}": 1 for i in range(MAX_PARAM_KEYS + 20)})
    assert len(got["keys"]) == MAX_PARAM_KEYS
    assert got["count"] == MAX_PARAM_KEYS + 20


# --- D1: the key summary rides on the row --------------------------------------------------

@pytest.mark.invariant("SEC-190")
def test_the_row_carries_the_key_names_and_neither_value():
    """[2026] VJS-CC-BOLTRIG-SCHEMA-VALIDATION-LEDGER-001 D1.

    Recorded keys are what make the diff in D5 possible at all."""
    parsed = json.loads(_row({"matter_id": "SENSITIVE-VALUE", "limit": "y"}, GET_MATTER_SCHEMA))
    assert parsed["params"] == {"keys": ["limit", "matter_id"], "count": 2}
    assert "SENSITIVE-VALUE" not in json.dumps(parsed)


# --- D9 and D10: the record about the record -----------------------------------------------

def test_the_vendored_citator_carries_the_orders_this_one_rests_on():
    """[2026] VJS-CC-BOLTRIG-SCHEMA-VALIDATION-LEDGER-001 D9.

    The two opbox orders whose ratios this judgment adopts as persuasive were absent from the
    vendored citator when it was written, so citing them would have failed the prose gate as
    though they did not exist.

    Refreshing to carry them found a second, larger defect and it is worth naming here because
    this test would not have caught it on its own: `refresh_canon_citations.py` read only
    canon's `.vjs/orders/`, and canon keeps ENACTED law under `lawpack/v2/orders/`. The count
    went from 59 citations to 159. `[2026] VJS-PC 20` happened to live in the first estate and
    vendored fine, which is exactly why nobody noticed that `[2026] VJS-PC 19` could not be
    cited at all.
    """
    from pathlib import Path

    citator = Path(__file__).resolve().parents[2] / ".vjs" / "canon-citations.txt"
    text = citator.read_text(encoding="utf-8")
    for cited in (
        "2026-VJS-CC-OPBOX-PSEUDONYMISER-VERB-SCOPE-004",
        "2026-VJS-CC-OPBOX-CREDENTIAL-AUDITED-PATH-005",
        "[2026] VJS-PC 19",
    ):
        assert cited in text, f"the citator cannot resolve {cited}"


def test_the_invariant_is_declared_and_points_at_this_file():
    """[2026] VJS-CC-BOLTRIG-SCHEMA-VALIDATION-LEDGER-001 D10.

    The catalogue is the thing the census gate reads, so a directive that ends in an invariant
    is only discharged once the row exists AND names tests that exist. `check_invariants.py`
    proves the second half; this proves the first, so a later edit that deletes the row fails
    here rather than quietly reducing the declared surface.
    """
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[2]
    cat = yaml.safe_load((root / "tests" / "invariants.yaml").read_text(encoding="utf-8"))
    rows = cat.get("invariants", cat)
    assert "SEC-190" in rows, "the schema-validation ledger invariant is not declared"
    tests = rows["SEC-190"]["tests"]
    assert tests and all("test_schema_validation_ledger.py" in t for t in tests)
