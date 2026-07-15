"""Canonical bounded values shared by run-scoped grant lease records."""

from __future__ import annotations

from datetime import datetime
import unicodedata

from boltrig.models import VerbId
from boltrig.models.grants import MAX_CONCRETE_VERBS, canonical_concrete_verbs

MAX_IDENTIFIER_LENGTH = 160
MAX_PERMITTED_VERBS = MAX_CONCRETE_VERBS
MAX_GRANT_TTL_SECONDS = 3600
MAX_REVOCATION_REASON_LENGTH = 160
MAX_SIGNED_BIGINT = 2**63 - 1


def _contains_control_character(value: str) -> bool:
    return any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for character in value
    )


def identifier(label: str, value: object) -> str:
    if type(value) is not str:
        raise TypeError(f"{label} must be an exact string")
    text = value
    if (
        not text
        or text != text.strip()
        or len(text) > MAX_IDENTIFIER_LENGTH
        or _contains_control_character(text)
    ):
        raise ValueError(f"{label} must be a bounded, control-free, trimmed identifier")
    return text


def aware(label: str, value: object) -> datetime:
    if type(value) is not datetime:
        raise TypeError(f"{label} must be an exact datetime")
    timestamp = value
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return timestamp


def positive_bigint(label: str, value: object) -> int:
    if type(value) is not int or not 1 <= value <= MAX_SIGNED_BIGINT:
        raise ValueError(f"{label} must be positive and fit a signed BIGINT")
    return value


def concrete_verbs(values: tuple[VerbId, ...]) -> tuple[VerbId, ...]:
    return canonical_concrete_verbs(values)


def raw_sha256_digest(label: str, value: str) -> str:
    identifier(label, value)
    if len(value) != 64 or value != value.lower():
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    try:
        bytes.fromhex(value)
    except ValueError:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest") from None
    return value


def prefixed_sha256_digest(label: str, value: str) -> str:
    identifier(label, value)
    if not value.startswith("sha256:"):
        raise ValueError(f"{label} must be a lowercase sha256 digest")
    raw_sha256_digest(label, value.removeprefix("sha256:"))
    return value


def validate_revocation_reason(value: str) -> str:
    """Validate the canonical bounded reason shared with durable SQL storage."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > MAX_REVOCATION_REASON_LENGTH
        or _contains_control_character(value)
    ):
        raise ValueError("revocation reason must be bounded, trimmed, and control-free")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("revocation reason must be valid UTF-8") from None
    return value


__all__ = [
    "MAX_GRANT_TTL_SECONDS",
    "MAX_IDENTIFIER_LENGTH",
    "MAX_PERMITTED_VERBS",
    "MAX_REVOCATION_REASON_LENGTH",
    "MAX_SIGNED_BIGINT",
    "aware",
    "concrete_verbs",
    "identifier",
    "positive_bigint",
    "prefixed_sha256_digest",
    "raw_sha256_digest",
    "validate_revocation_reason",
]
