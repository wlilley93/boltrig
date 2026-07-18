"""Strict local parser for the pinned Codex phase-result contract."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from typing import Never, cast

from boltrig.fleet.domain.phase_results import (
    MAX_BLOCKER_ITEMS,
    MAX_COMPLETION_SUMMARY_CHARS,
    MAX_EVIDENCE_ITEMS,
    MAX_EVIDENCE_REFS,
    MAX_FINDING_ITEMS,
    MAX_HANDOFF_ITEMS,
    MAX_IDENTIFIER_CHARS,
    MAX_NARRATIVE_CHARS,
    NormalizedPhaseBlocker,
    NormalizedPhaseFinding,
    NormalizedPhaseHandoff,
    NormalizedPhaseResult,
    PhaseCompletionStatus,
    PhaseFindingSeverity,
    PhaseResultContractRef,
    PhaseResultParseOutcome,
    PhaseResultRejection,
    PhaseResultRejectionCode,
    TransientPhaseResultCandidate,
    UnresolvedEvidenceRef,
    UnresolvedProfileRef,
)
from .codex_phase_result_schema import (
    PHASE_RESULT_SCHEMA_DIGEST,
    PHASE_RESULT_SCHEMA_VERSION,
    strict_phase_result_document,
)

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}\Z")
_SEMVER = re.compile(
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)"
    r"(?:-(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z"
)


class _CandidateRejected(Exception):
    def __init__(self, code: PhaseResultRejectionCode) -> None:
        super().__init__(code.value)
        self.code = code


def parse_codex_phase_result(candidate: object) -> PhaseResultParseOutcome:
    """Parse a transient candidate without ever returning worker narrative text."""

    if type(candidate) is not TransientPhaseResultCandidate:
        raise TypeError("candidate must be an exact TransientPhaseResultCandidate")
    raw = candidate._copy_for_parser()
    document = strict_phase_result_document(raw)
    if type(document) is PhaseResultRejection:
        return document
    try:
        return _normalize(document)
    except _CandidateRejected as rejected:
        return PhaseResultRejection(rejected.code)


def _normalize(value: object) -> NormalizedPhaseResult:
    document = _object(
        value,
        {"schemaVersion", "completion", "evidence", "findings", "blockers", "handoffs"},
    )
    if _string(document["schemaVersion"]) != PHASE_RESULT_SCHEMA_VERSION:
        _reject(PhaseResultRejectionCode.SCHEMA_VIOLATION)
    completion_doc = _object(document["completion"], {"status", "summary"})
    status_text = _string(completion_doc["status"])
    if status_text not in {status.value for status in PhaseCompletionStatus}:
        _reject(PhaseResultRejectionCode.SCHEMA_VIOLATION)
    completion = PhaseCompletionStatus(status_text)
    completion_summary = _narrative(completion_doc["summary"], maximum=MAX_COMPLETION_SUMMARY_CHARS)

    evidence, normalized_evidence = _parse_evidence(document["evidence"])
    findings, normalized_findings = _parse_findings(document["findings"])
    blockers, normalized_blockers = _parse_blockers(document["blockers"])
    handoffs, normalized_handoffs = _parse_handoffs(document["handoffs"])
    _validate_semantics(completion, evidence, findings, blockers, handoffs)

    normalized_document: dict[str, object] = {
        "blockers": normalized_blockers,
        "completion": {"status": completion.value, "summary": completion_summary},
        "evidence": normalized_evidence,
        "findings": normalized_findings,
        "handoffs": normalized_handoffs,
        "schemaVersion": PHASE_RESULT_SCHEMA_VERSION,
    }
    normalized_bytes = json.dumps(
        normalized_document,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return NormalizedPhaseResult(
        contract=PhaseResultContractRef(PHASE_RESULT_SCHEMA_VERSION, PHASE_RESULT_SCHEMA_DIGEST),
        completion=completion,
        completion_summary_digest=_digest(completion_summary),
        evidence=evidence,
        findings=findings,
        blockers=blockers,
        handoffs=handoffs,
        normalized_digest=_digest_bytes(normalized_bytes),
    )


def _parse_evidence(value: object) -> tuple[tuple[UnresolvedEvidenceRef, ...], list[object]]:
    items = _array(value, MAX_EVIDENCE_ITEMS)
    refs = tuple(
        UnresolvedEvidenceRef(_identifier(_object(item, {"evidenceId"})["evidenceId"]))
        for item in items
    )
    _unique((item.evidence_id for item in refs))
    ordered = tuple(sorted(refs, key=lambda item: item.evidence_id))
    return ordered, [{"evidenceId": item.evidence_id} for item in ordered]


def _parse_findings(
    value: object,
) -> tuple[tuple[NormalizedPhaseFinding, ...], list[object]]:
    parsed: list[tuple[NormalizedPhaseFinding, dict[str, object]]] = []
    required = {"code", "severity", "summary", "detail", "evidenceIds"}
    for item in _array(value, MAX_FINDING_ITEMS):
        entry = _object(item, required)
        code = _identifier(entry["code"])
        severity_text = _string(entry["severity"])
        if severity_text not in {severity.value for severity in PhaseFindingSeverity}:
            _reject(PhaseResultRejectionCode.SCHEMA_VIOLATION)
        summary = _narrative(entry["summary"], maximum=MAX_NARRATIVE_CHARS)
        detail = _narrative(entry["detail"], maximum=MAX_NARRATIVE_CHARS)
        refs, ref_ids = _evidence_refs(entry["evidenceIds"])
        parsed.append(
            (
                NormalizedPhaseFinding(
                    code,
                    PhaseFindingSeverity(severity_text),
                    _digest(summary),
                    _digest(detail),
                    refs,
                ),
                {
                    "code": code,
                    "detail": detail,
                    "evidenceIds": ref_ids,
                    "severity": severity_text,
                    "summary": summary,
                },
            )
        )
    _unique((item[0].code for item in parsed))
    parsed.sort(key=lambda item: item[0].code)
    return tuple(item[0] for item in parsed), [item[1] for item in parsed]


def _parse_blockers(
    value: object,
) -> tuple[tuple[NormalizedPhaseBlocker, ...], list[object]]:
    parsed: list[tuple[NormalizedPhaseBlocker, dict[str, object]]] = []
    for item in _array(value, MAX_BLOCKER_ITEMS):
        entry = _object(item, {"code", "summary", "detail", "evidenceIds"})
        code = _identifier(entry["code"])
        summary = _narrative(entry["summary"], maximum=MAX_NARRATIVE_CHARS)
        detail = _narrative(entry["detail"], maximum=MAX_NARRATIVE_CHARS)
        refs, ref_ids = _evidence_refs(entry["evidenceIds"])
        parsed.append(
            (
                NormalizedPhaseBlocker(code, _digest(summary), _digest(detail), refs),
                {"code": code, "detail": detail, "evidenceIds": ref_ids, "summary": summary},
            )
        )
    _unique((item[0].code for item in parsed))
    parsed.sort(key=lambda item: item[0].code)
    return tuple(item[0] for item in parsed), [item[1] for item in parsed]


def _parse_handoffs(
    value: object,
) -> tuple[tuple[NormalizedPhaseHandoff, ...], list[object]]:
    parsed: list[tuple[NormalizedPhaseHandoff, dict[str, object]]] = []
    for item in _array(value, MAX_HANDOFF_ITEMS):
        entry = _object(item, {"profile", "summary", "evidenceIds"})
        profile_doc = _object(entry["profile"], {"name", "version"})
        name = _identifier(profile_doc["name"])
        version = _semver(profile_doc["version"])
        summary = _narrative(entry["summary"], maximum=MAX_NARRATIVE_CHARS)
        refs, ref_ids = _evidence_refs(entry["evidenceIds"])
        profile = UnresolvedProfileRef(name, version)
        parsed.append(
            (
                NormalizedPhaseHandoff(profile, _digest(summary), refs),
                {
                    "evidenceIds": ref_ids,
                    "profile": {"name": name, "version": version},
                    "summary": summary,
                },
            )
        )
    _unique((f"{item[0].profile.name}\0{item[0].profile.version}" for item in parsed))
    parsed.sort(key=lambda item: (item[0].profile.name, item[0].profile.version))
    return tuple(item[0] for item in parsed), [item[1] for item in parsed]


def _evidence_refs(value: object) -> tuple[tuple[UnresolvedEvidenceRef, ...], list[str]]:
    identifiers = tuple(_identifier(item) for item in _array(value, MAX_EVIDENCE_REFS))
    _unique(identifiers)
    ordered = sorted(identifiers)
    return tuple(UnresolvedEvidenceRef(item) for item in ordered), ordered


def _validate_semantics(
    completion: PhaseCompletionStatus,
    evidence: tuple[UnresolvedEvidenceRef, ...],
    findings: tuple[NormalizedPhaseFinding, ...],
    blockers: tuple[NormalizedPhaseBlocker, ...],
    handoffs: tuple[NormalizedPhaseHandoff, ...],
) -> None:
    if completion is PhaseCompletionStatus.COMPLETED and blockers:
        _reject(PhaseResultRejectionCode.SEMANTIC_VIOLATION)
    if completion is PhaseCompletionStatus.BLOCKED and not blockers:
        _reject(PhaseResultRejectionCode.SEMANTIC_VIOLATION)
    _unique([item.code for item in findings] + [item.code for item in blockers])
    declared = {item.evidence_id for item in evidence}
    sources: tuple[
        NormalizedPhaseFinding | NormalizedPhaseBlocker | NormalizedPhaseHandoff, ...
    ] = (*findings, *blockers, *handoffs)
    referenced = {ref.evidence_id for entry in sources for ref in entry.evidence}
    if referenced != declared:
        _reject(PhaseResultRejectionCode.SEMANTIC_VIOLATION)


def _object(value: object, keys: set[str]) -> dict[str, object]:
    if type(value) is not dict:
        _reject(PhaseResultRejectionCode.SCHEMA_VIOLATION)
    document = cast(dict[str, object], value)
    if set(document) != keys:
        _reject(PhaseResultRejectionCode.SCHEMA_VIOLATION)
    return document


def _array(value: object, maximum: int) -> list[object]:
    if type(value) is not list:
        _reject(PhaseResultRejectionCode.SCHEMA_VIOLATION)
    items = cast(list[object], value)
    if len(items) > maximum:
        _reject(PhaseResultRejectionCode.BOUNDS_EXCEEDED)
    return items


def _string(value: object) -> str:
    if type(value) is not str:
        _reject(PhaseResultRejectionCode.SCHEMA_VIOLATION)
    return value


def _identifier(value: object) -> str:
    text = _string(value)
    if len(text) > MAX_IDENTIFIER_CHARS:
        _reject(PhaseResultRejectionCode.BOUNDS_EXCEEDED)
    if _IDENTIFIER.fullmatch(text) is None:
        _reject(PhaseResultRejectionCode.SCHEMA_VIOLATION)
    return text


def _semver(value: object) -> str:
    text = _string(value)
    if len(text) > MAX_IDENTIFIER_CHARS:
        _reject(PhaseResultRejectionCode.BOUNDS_EXCEEDED)
    if _SEMVER.fullmatch(text) is None:
        _reject(PhaseResultRejectionCode.SCHEMA_VIOLATION)
    return text


def _narrative(value: object, *, maximum: int) -> str:
    text = _string(value)
    if len(text) > maximum:
        _reject(PhaseResultRejectionCode.BOUNDS_EXCEEDED)
    if not text or text != text.strip():
        _reject(PhaseResultRejectionCode.UNSAFE_TEXT)
    return text


def _unique(values: Iterable[str]) -> None:
    entries = tuple(values)
    if len(entries) != len(set(entries)):
        _reject(PhaseResultRejectionCode.SEMANTIC_VIOLATION)


def _digest(text: str) -> str:
    return _digest_bytes(text.encode("utf-8"))


def _digest_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _reject(code: PhaseResultRejectionCode) -> Never:
    raise _CandidateRejected(code)


__all__ = ["parse_codex_phase_result"]
