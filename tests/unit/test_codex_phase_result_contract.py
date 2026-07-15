from __future__ import annotations

import hashlib
import json
import pickle
from copy import deepcopy
from typing import cast

import pytest
from jsonschema import Draft202012Validator

from boltrig.fleet.domain.json_types import JSONValue
from boltrig.fleet.domain.phase_results import (
    MAX_PHASE_RESULT_BYTES,
    NormalizedPhaseResult,
    PhaseCompletionStatus,
    PhaseResultContractRef,
    PhaseResultRejection,
    PhaseResultRejectionCode,
    TransientPhaseResultCandidate,
)
from boltrig.fleet.infrastructure.codex_phase_result_parser import parse_codex_phase_result
from boltrig.fleet.infrastructure.codex_phase_result_schema import (
    PHASE_RESULT_SCHEMA_DIGEST,
    PHASE_RESULT_SCHEMA_VERSION,
    phase_result_output_schema,
)


def _document(*, blocked: bool = False) -> dict[str, object]:
    blockers: list[object] = []
    if blocked:
        blockers.append(
            {
                "code": "waiting.approval",
                "summary": "Approval is required",
                "detail": "A governed write cannot proceed",
                "evidenceIds": ["audit.approval"],
            }
        )
    return {
        "schemaVersion": PHASE_RESULT_SCHEMA_VERSION,
        "completion": {
            "status": "blocked" if blocked else "completed",
            "summary": "The bounded analysis is complete" if not blocked else "Work is paused",
        },
        "evidence": [
            {"evidenceId": "test.output"},
            {"evidenceId": "audit.approval"},
        ],
        "findings": [
            {
                "code": "finding.zeta",
                "severity": "low",
                "summary": "One condition was observed",
                "detail": "The condition is locally reproducible",
                "evidenceIds": ["test.output"],
            }
        ],
        "blockers": blockers,
        "handoffs": [
            {
                "profile": {"name": "head_of_legal", "version": "1.2.3-beta.1+build.7"},
                "summary": "Review the collected evidence",
                "evidenceIds": ["audit.approval"] if not blocked else [],
            }
        ],
    }


def _candidate(document: object) -> TransientPhaseResultCandidate:
    encoded = json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return TransientPhaseResultCandidate(encoded)


def _parse(document: object) -> NormalizedPhaseResult | PhaseResultRejection:
    return parse_codex_phase_result(_candidate(document))


def _rejection(document: object, code: PhaseResultRejectionCode) -> None:
    outcome = _parse(document)
    assert outcome == PhaseResultRejection(code)
    assert not hasattr(outcome, "normalized_digest")


def test_schema_is_pinned_valid_and_matches_the_successful_wire_document() -> None:
    schema_value = phase_result_output_schema().to_mapping()
    Draft202012Validator.check_schema(schema_value)
    Draft202012Validator(schema_value).validate(_document())
    encoded = json.dumps(
        schema_value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    assert PHASE_RESULT_SCHEMA_DIGEST == (
        "sha256:d32c15e2660f95da571a72cfd18741fe3a04819c39c335d85761ac484954aebe"
    )
    assert PHASE_RESULT_SCHEMA_DIGEST == f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def test_success_is_digest_only_and_array_order_is_normalized() -> None:
    document = _document()
    outcome = _parse(document)
    assert type(outcome) is NormalizedPhaseResult
    assert outcome.completion is PhaseCompletionStatus.COMPLETED
    assert tuple(item.evidence_id for item in outcome.evidence) == (
        "audit.approval",
        "test.output",
    )
    assert outcome.handoffs[0].profile.version == "1.2.3-beta.1+build.7"
    assert outcome.completion_summary_digest == (
        "sha256:8f6789b3e21664a7ece677f1c85d2ab84982acf957fc0a3dc3fb1c5e0fcbc672"
    )
    rendered = repr(outcome)
    assert "bounded analysis" not in rendered
    assert "condition is locally" not in rendered
    assert "Review the collected" not in rendered

    reordered = deepcopy(document)
    cast(list[object], reordered["evidence"]).reverse()
    normalized_again = _parse(reordered)
    assert type(normalized_again) is NormalizedPhaseResult
    assert normalized_again.normalized_digest == outcome.normalized_digest


def test_blocked_result_requires_and_preserves_only_blocker_digests() -> None:
    outcome = _parse(_document(blocked=True))
    assert type(outcome) is NormalizedPhaseResult
    assert outcome.completion is PhaseCompletionStatus.BLOCKED
    assert outcome.blockers[0].code == "waiting.approval"
    assert "governed write" not in repr(outcome)


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (b"\xff", PhaseResultRejectionCode.INVALID_ENCODING),
        (b"{", PhaseResultRejectionCode.INVALID_JSON),
        (b'{"x":1,"x":2}', PhaseResultRejectionCode.DUPLICATE_KEY),
        (b'{"x":NaN}', PhaseResultRejectionCode.NONFINITE_NUMBER),
        (b'{ "x":1}', PhaseResultRejectionCode.NONCANONICAL_JSON),
        (b"[" * 2_000 + b"]" * 2_000, PhaseResultRejectionCode.BOUNDS_EXCEEDED),
        (b"x" * (MAX_PHASE_RESULT_BYTES + 1), PhaseResultRejectionCode.DOCUMENT_TOO_LARGE),
    ],
)
def test_wire_rejections_are_stable_and_never_digest_raw_text(
    raw: bytes, code: PhaseResultRejectionCode
) -> None:
    outcome = parse_codex_phase_result(TransientPhaseResultCandidate(raw))
    assert outcome == PhaseResultRejection(code)
    assert not hasattr(outcome, "normalized_digest")
    prefix = raw[:16].decode("utf-8", errors="ignore")
    if prefix:
        assert prefix not in repr(outcome)


@pytest.mark.parametrize("unsafe", ["Cafe\u0301", "line\nbreak", "left\u202eright", "x\u2028y"])
def test_non_nfc_control_bidi_and_separator_text_is_rejected(unsafe: str) -> None:
    document = _document()
    cast(dict[str, object], document["completion"])["summary"] = unsafe
    _rejection(document, PhaseResultRejectionCode.UNSAFE_TEXT)


def test_depth_node_collection_and_field_bounds_are_enforced() -> None:
    too_deep: object = "leaf"
    for _ in range(9):
        too_deep = [too_deep]
    _rejection({"extra": too_deep}, PhaseResultRejectionCode.BOUNDS_EXCEEDED)
    _rejection({"extra": [0] * 512}, PhaseResultRejectionCode.BOUNDS_EXCEEDED)

    too_many = _document()
    too_many["evidence"] = [{"evidenceId": f"evidence.{index}"} for index in range(65)]
    _rejection(too_many, PhaseResultRejectionCode.BOUNDS_EXCEEDED)

    long_narrative = _document()
    cast(dict[str, object], cast(list[object], long_narrative["findings"])[0])["summary"] = (
        "x" * 2049
    )
    _rejection(long_narrative, PhaseResultRejectionCode.BOUNDS_EXCEEDED)

    long_identifier = _document()
    cast(dict[str, object], cast(list[object], long_identifier["evidence"])[0])["evidenceId"] = (
        "x" * 161
    )
    _rejection(long_identifier, PhaseResultRejectionCode.BOUNDS_EXCEEDED)


def test_exact_shape_types_enums_and_semver_are_enforced() -> None:
    for mutation in ("extra", "missing", "wrong_type", "bad_enum", "bad_semver"):
        document = _document()
        if mutation == "extra":
            document["authority"] = "write"
        elif mutation == "missing":
            del document["findings"]
        elif mutation == "wrong_type":
            document["evidence"] = True
        elif mutation == "bad_enum":
            cast(dict[str, object], document["completion"])["status"] = "succeeded"
        else:
            handoff = cast(dict[str, object], cast(list[object], document["handoffs"])[0])
            cast(dict[str, object], handoff["profile"])["version"] = "01.2.3"
        _rejection(document, PhaseResultRejectionCode.SCHEMA_VIOLATION)


def test_completion_evidence_code_and_handoff_semantics_fail_closed() -> None:
    completed_with_blocker = _document(blocked=True)
    cast(dict[str, object], completed_with_blocker["completion"])["status"] = "completed"
    _rejection(completed_with_blocker, PhaseResultRejectionCode.SEMANTIC_VIOLATION)

    blocked_without_blocker = _document()
    cast(dict[str, object], blocked_without_blocker["completion"])["status"] = "blocked"
    _rejection(blocked_without_blocker, PhaseResultRejectionCode.SEMANTIC_VIOLATION)

    unknown_ref = _document()
    finding = cast(dict[str, object], cast(list[object], unknown_ref["findings"])[0])
    finding["evidenceIds"] = ["unknown.evidence"]
    _rejection(unknown_ref, PhaseResultRejectionCode.SEMANTIC_VIOLATION)

    unreferenced = _document()
    cast(list[object], unreferenced["handoffs"])[0] = {
        "profile": {"name": "head_of_legal", "version": "1.2.3"},
        "summary": "Review the result",
        "evidenceIds": [],
    }
    _rejection(unreferenced, PhaseResultRejectionCode.SEMANTIC_VIOLATION)

    duplicate_code = _document(blocked=True)
    blocker = cast(dict[str, object], cast(list[object], duplicate_code["blockers"])[0])
    blocker["code"] = "finding.zeta"
    _rejection(duplicate_code, PhaseResultRejectionCode.SEMANTIC_VIOLATION)

    duplicate_handoff = _document()
    cast(list[object], duplicate_handoff["handoffs"]).append(
        deepcopy(cast(list[object], duplicate_handoff["handoffs"])[0])
    )
    _rejection(duplicate_handoff, PhaseResultRejectionCode.SEMANTIC_VIOLATION)


@pytest.mark.parametrize(
    ("location", "secret"),
    [
        ("completion", "Bearer abcdefghijklmnopqrstuvwxyz"),
        ("finding_summary", "sk-abcdefghijklmnopqrstuvwx"),
        ("finding_detail", "-----BEGIN ENCRYPTED PRIVATE KEY-----"),
        ("blocker_summary", "Cookie: session=abcdefghijklmnop"),
        ("blocker_detail", "password=hunter2"),
        ("handoff", "kP3xQ9zR2mN7bV4cX1wL8sT6yU0aE5dF9gH2jK4lM6n"),
    ],
)
def test_credentials_in_every_narrative_position_leave_only_server_code(
    location: str, secret: str
) -> None:
    document = _document(blocked=True)
    completion = cast(dict[str, object], document["completion"])
    finding = cast(dict[str, object], cast(list[object], document["findings"])[0])
    blocker = cast(dict[str, object], cast(list[object], document["blockers"])[0])
    handoff = cast(dict[str, object], cast(list[object], document["handoffs"])[0])
    targets = {
        "completion": (completion, "summary"),
        "finding_summary": (finding, "summary"),
        "finding_detail": (finding, "detail"),
        "blocker_summary": (blocker, "summary"),
        "blocker_detail": (blocker, "detail"),
        "handoff": (handoff, "summary"),
    }
    target, key = targets[location]
    target[key] = secret
    outcome = _parse(document)
    assert outcome == PhaseResultRejection(PhaseResultRejectionCode.CREDENTIAL_DETECTED)
    assert secret not in repr(outcome)
    assert not hasattr(outcome, "normalized_digest")


@pytest.mark.parametrize(
    "secret",
    [
        "Authorization: Basic QWxhZGRpbjpvcGVuIHNlc2FtZQ==",
        "ａｃｃｅｓｓＴｏｋｅｎ=abcdefghijklmnop",
        "Set-Cookie: sessionid=abcdefghijklmnop",
        "access token: hunter2",
        "api key=hunter2",
        "private key is hunter2",
        "refresh token=hunter2",
        "auth token: hunter2",
        "session token = hunter2",
        "session id = hunter2",
        "sessionid = hunter2",
        "sid=hunter2",
        "Bearer hunter2",
    ],
)
def test_compatibility_spelling_and_additional_credential_forms_are_rejected(secret: str) -> None:
    document = _document()
    cast(dict[str, object], document["completion"])["summary"] = secret
    outcome = _parse(document)
    assert outcome == PhaseResultRejection(PhaseResultRejectionCode.CREDENTIAL_DETECTED)


@pytest.mark.parametrize(
    "location",
    [
        "schema_version",
        "evidence_id",
        "finding_code",
        "blocker_code",
        "profile_name",
        "profile_version",
        "object_key",
    ],
)
def test_token_shaped_credentials_are_rejected_in_every_retained_string(location: str) -> None:
    secret = "sk-abcdefghijklmnopqrstuvwx"
    document = _document(blocked=True)
    evidence = cast(dict[str, object], cast(list[object], document["evidence"])[0])
    finding = cast(dict[str, object], cast(list[object], document["findings"])[0])
    blocker = cast(dict[str, object], cast(list[object], document["blockers"])[0])
    handoff = cast(dict[str, object], cast(list[object], document["handoffs"])[0])
    profile = cast(dict[str, object], handoff["profile"])
    if location == "schema_version":
        document["schemaVersion"] = secret
    elif location == "evidence_id":
        evidence["evidenceId"] = secret
        finding["evidenceIds"] = [secret]
    elif location == "finding_code":
        finding["code"] = secret
    elif location == "blocker_code":
        blocker["code"] = secret
    elif location == "profile_name":
        profile["name"] = secret
    elif location == "profile_version":
        profile["version"] = secret
    else:
        document[secret] = "safe"
    outcome = _parse(document)
    assert outcome == PhaseResultRejection(PhaseResultRejectionCode.CREDENTIAL_DETECTED)
    assert not hasattr(outcome, "normalized_digest")
    assert secret not in repr(outcome)


def test_transient_candidate_is_exact_redacted_and_nonserializable() -> None:
    sentinel = b"never-log-this-final-answer"
    candidate = TransientPhaseResultCandidate(sentinel)
    assert sentinel.decode() not in repr(candidate)
    assert sentinel.decode() not in str(candidate)
    with pytest.raises(TypeError, match="cannot be serialized"):
        pickle.dumps(candidate)
    with pytest.raises(TypeError, match="exact immutable bytes"):
        TransientPhaseResultCandidate(bytearray(sentinel))  # type: ignore[arg-type]

    class CandidateSubclass(TransientPhaseResultCandidate):
        pass

    with pytest.raises(TypeError, match="exact TransientPhaseResultCandidate"):
        parse_codex_phase_result(CandidateSubclass(sentinel))


def test_contract_reference_rejects_string_subclasses() -> None:
    class StringSubclass(str):
        pass

    with pytest.raises(TypeError, match="exact string"):
        PhaseResultContractRef(
            StringSubclass(PHASE_RESULT_SCHEMA_VERSION), PHASE_RESULT_SCHEMA_DIGEST
        )
    with pytest.raises(TypeError, match="exact string"):
        PhaseResultContractRef(
            PHASE_RESULT_SCHEMA_VERSION, StringSubclass(PHASE_RESULT_SCHEMA_DIGEST)
        )
    with pytest.raises(ValueError, match="pinned schema version"):
        PhaseResultContractRef(PHASE_RESULT_SCHEMA_VERSION, f"sha256:{'0' * 64}")


def test_output_schema_returns_an_isolated_copy() -> None:
    first = phase_result_output_schema().to_mapping()
    first["type"] = cast(JSONValue, "array")
    assert phase_result_output_schema().to_mapping()["type"] == "object"
