"""Pinned JSON Schema injected for Codex phase final answers."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import unicodedata
from collections.abc import Iterable
from typing import Final, Never, cast

from boltrig.fleet.domain.json_types import CanonicalJSON
from boltrig.fleet.domain.phase_results import (
    MAX_BLOCKER_ITEMS,
    MAX_COMPLETION_SUMMARY_CHARS,
    MAX_EVIDENCE_ITEMS,
    MAX_EVIDENCE_REFS,
    MAX_FINDING_ITEMS,
    MAX_HANDOFF_ITEMS,
    MAX_IDENTIFIER_CHARS,
    MAX_NARRATIVE_CHARS,
    MAX_PHASE_RESULT_BYTES,
    MAX_PHASE_RESULT_DEPTH,
    MAX_PHASE_RESULT_NODES,
    PHASE_RESULT_V1_SCHEMA_DIGEST,
    PhaseResultRejection,
    PhaseResultRejectionCode,
)
from boltrig.kernel.pii import contains_secret

PHASE_RESULT_SCHEMA_VERSION: Final = "boltrig.phase-result.v1"
PHASE_RESULT_SCHEMA_DIGEST: Final = PHASE_RESULT_V1_SCHEMA_DIGEST

_IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$"
_SEMVER_PATTERN = (
    r"^(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)"
    r"(?:-(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_UNSAFE_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[ _-]?key|access[ _-]?token|auth[ _-]?token|refresh[ _-]?token|"
    r"session[ _-]?token|authorization|client[ _-]?secret|password|passwd|secret|"
    r"private[ _-]?key)(?:\s*[:=]\s*|\s+is\s+)\S+"
)
_COOKIE_MATERIAL = re.compile(
    r"(?i)(?:\b(?:set[ _-]?cookie|cookie)\s*[:=]\s*\S+|"
    r"\b(?:j?session[ _-]?id|session[ _-]?token|phpsessid|sid)\s*=\s*\S+)"
)
_PRIVATE_KEY_BLOCK = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
_BEARER_MATERIAL = re.compile(r"(?i)\bbearer(?:\s+|\s*:\s*)\S+")


class _DocumentRejected(Exception):
    def __init__(self, code: PhaseResultRejectionCode) -> None:
        super().__init__(code.value)
        self.code = code


def _identifier() -> dict[str, object]:
    return {
        "type": "string",
        "minLength": 1,
        "maxLength": MAX_IDENTIFIER_CHARS,
        "pattern": _IDENTIFIER_PATTERN,
    }


def _narrative(maximum: int) -> dict[str, object]:
    return {"type": "string", "minLength": 1, "maxLength": maximum}


def _evidence_ids() -> dict[str, object]:
    return {
        "type": "array",
        "items": _identifier(),
        "maxItems": MAX_EVIDENCE_REFS,
        "uniqueItems": True,
    }


_SCHEMA_DOCUMENT: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schemaVersion",
        "completion",
        "evidence",
        "findings",
        "blockers",
        "handoffs",
    ],
    "properties": {
        "schemaVersion": {"const": PHASE_RESULT_SCHEMA_VERSION, "type": "string"},
        "completion": {
            "type": "object",
            "additionalProperties": False,
            "required": ["status", "summary"],
            "properties": {
                "status": {"enum": ["completed", "blocked"], "type": "string"},
                "summary": _narrative(MAX_COMPLETION_SUMMARY_CHARS),
            },
        },
        "evidence": {
            "type": "array",
            "maxItems": MAX_EVIDENCE_ITEMS,
            "uniqueItems": True,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["evidenceId"],
                "properties": {"evidenceId": _identifier()},
            },
        },
        "findings": {
            "type": "array",
            "maxItems": MAX_FINDING_ITEMS,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["code", "severity", "summary", "detail", "evidenceIds"],
                "properties": {
                    "code": _identifier(),
                    "severity": {
                        "enum": ["info", "low", "medium", "high", "critical"],
                        "type": "string",
                    },
                    "summary": _narrative(MAX_NARRATIVE_CHARS),
                    "detail": _narrative(MAX_NARRATIVE_CHARS),
                    "evidenceIds": _evidence_ids(),
                },
            },
        },
        "blockers": {
            "type": "array",
            "maxItems": MAX_BLOCKER_ITEMS,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["code", "summary", "detail", "evidenceIds"],
                "properties": {
                    "code": _identifier(),
                    "summary": _narrative(MAX_NARRATIVE_CHARS),
                    "detail": _narrative(MAX_NARRATIVE_CHARS),
                    "evidenceIds": _evidence_ids(),
                },
            },
        },
        "handoffs": {
            "type": "array",
            "maxItems": MAX_HANDOFF_ITEMS,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["profile", "summary", "evidenceIds"],
                "properties": {
                    "profile": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["name", "version"],
                        "properties": {
                            "name": _identifier(),
                            "version": {
                                "type": "string",
                                "minLength": 5,
                                "maxLength": MAX_IDENTIFIER_CHARS,
                                "pattern": _SEMVER_PATTERN,
                            },
                        },
                    },
                    "summary": _narrative(MAX_NARRATIVE_CHARS),
                    "evidenceIds": _evidence_ids(),
                },
            },
        },
    },
}

_SCHEMA_BYTES = json.dumps(
    _SCHEMA_DOCUMENT,
    allow_nan=False,
    ensure_ascii=False,
    separators=(",", ":"),
    sort_keys=True,
).encode("utf-8")


def phase_result_output_schema() -> CanonicalJSON:
    """Return an isolated immutable copy of the pinned output schema."""

    return CanonicalJSON(_SCHEMA_BYTES)


def strict_phase_result_document(raw: bytes) -> object | PhaseResultRejection:
    """Decode, bound, canonicalize, and credential-screen transient bytes."""

    if type(raw) is not bytes:
        raise TypeError("raw phase result must be exact immutable bytes")
    try:
        if len(raw) > MAX_PHASE_RESULT_BYTES:
            _reject(PhaseResultRejectionCode.DOCUMENT_TOO_LARGE)
        document = _decode(raw)
        _validate_tree(document, depth=0, budget=[0])
        _require_canonical(raw, document)
        _reject_credentials(document)
        return document
    except _DocumentRejected as rejected:
        return PhaseResultRejection(rejected.code)


def _decode(raw: bytes) -> object:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _reject(PhaseResultRejectionCode.INVALID_ENCODING)
    try:
        return cast(
            object,
            json.loads(
                text,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_nonfinite,
            ),
        )
    except _DocumentRejected:
        raise
    except RecursionError:
        _reject(PhaseResultRejectionCode.BOUNDS_EXCEEDED)
    except (json.JSONDecodeError, OverflowError, ValueError):
        _reject(PhaseResultRejectionCode.INVALID_JSON)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _reject(PhaseResultRejectionCode.DUPLICATE_KEY)
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> Never:
    del value
    _reject(PhaseResultRejectionCode.NONFINITE_NUMBER)


def _validate_tree(value: object, *, depth: int, budget: list[int]) -> None:
    budget[0] += 1
    if budget[0] > MAX_PHASE_RESULT_NODES or depth > MAX_PHASE_RESULT_DEPTH:
        _reject(PhaseResultRejectionCode.BOUNDS_EXCEEDED)
    if type(value) is str:
        _safe_unicode(value)
        return
    if value is None or type(value) in {bool, int}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            _reject(PhaseResultRejectionCode.NONFINITE_NUMBER)
        return
    if type(value) is list:
        for item in cast(list[object], value):
            _validate_tree(item, depth=depth + 1, budget=budget)
        return
    if type(value) is dict:
        for key, item in cast(dict[str, object], value).items():
            _safe_unicode(key)
            _validate_tree(item, depth=depth + 1, budget=budget)
        return
    _reject(PhaseResultRejectionCode.SCHEMA_VIOLATION)


def _safe_unicode(value: str) -> None:
    if value != unicodedata.normalize("NFC", value):
        _reject(PhaseResultRejectionCode.UNSAFE_TEXT)
    if any(unicodedata.category(character) in _UNSAFE_CATEGORIES for character in value):
        _reject(PhaseResultRejectionCode.UNSAFE_TEXT)


def _require_canonical(raw: bytes, document: object) -> None:
    try:
        encoded = json.dumps(
            document,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        _reject(PhaseResultRejectionCode.INVALID_JSON)
    if encoded != raw:
        _reject(PhaseResultRejectionCode.NONCANONICAL_JSON)


def _reject_credentials(document: object) -> None:
    for text in _all_strings(document):
        compatible = unicodedata.normalize("NFKC", text)
        for candidate in (text, compatible):
            secret_kind = contains_secret(candidate)
            if (
                (secret_kind is not None and secret_kind != "email")
                or _CREDENTIAL_ASSIGNMENT.search(candidate) is not None
                or _COOKIE_MATERIAL.search(candidate) is not None
                or _PRIVATE_KEY_BLOCK.search(candidate) is not None
                or _BEARER_MATERIAL.search(candidate) is not None
            ):
                _reject(PhaseResultRejectionCode.CREDENTIAL_DETECTED)


def _all_strings(value: object) -> Iterable[str]:
    if type(value) is str:
        yield value
    elif type(value) is list:
        for item in cast(list[object], value):
            yield from _all_strings(item)
    elif type(value) is dict:
        for key, item in cast(dict[str, object], value).items():
            yield key
            yield from _all_strings(item)


def _reject(code: PhaseResultRejectionCode) -> Never:
    raise _DocumentRejected(code)


def _verify_pin() -> None:
    actual = f"sha256:{hashlib.sha256(_SCHEMA_BYTES).hexdigest()}"
    if not hmac.compare_digest(actual, PHASE_RESULT_SCHEMA_DIGEST):
        raise RuntimeError("pinned phase result schema digest does not match schema")


_verify_pin()

__all__ = [
    "PHASE_RESULT_SCHEMA_DIGEST",
    "PHASE_RESULT_SCHEMA_VERSION",
    "phase_result_output_schema",
    "strict_phase_result_document",
]
