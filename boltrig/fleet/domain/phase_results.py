"""Safe domain values produced from a transient Codex phase result."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Final, Never, SupportsIndex, TypeVar, cast

MAX_PHASE_RESULT_BYTES: Final = 32_768
MAX_PHASE_RESULT_DEPTH: Final = 8
MAX_PHASE_RESULT_NODES: Final = 512
MAX_EVIDENCE_ITEMS: Final = 64
MAX_FINDING_ITEMS: Final = 64
MAX_BLOCKER_ITEMS: Final = 32
MAX_HANDOFF_ITEMS: Final = 16
MAX_EVIDENCE_REFS: Final = 32
MAX_IDENTIFIER_CHARS: Final = 160
MAX_NARRATIVE_CHARS: Final = 2_048
MAX_COMPLETION_SUMMARY_CHARS: Final = 4_096
PHASE_RESULT_V1_SCHEMA_DIGEST: Final = (
    "sha256:d32c15e2660f95da571a72cfd18741fe3a04819c39c335d85761ac484954aebe"
)

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}\Z")
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SEMVER = re.compile(
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)"
    r"(?:-(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z"
)
_SortableKey = TypeVar("_SortableKey", str, tuple[str, str])


class PhaseCompletionStatus(str, Enum):
    COMPLETED = "completed"
    BLOCKED = "blocked"


class PhaseFindingSeverity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PhaseResultRejectionCode(str, Enum):
    """Stable, server-owned rejection codes that disclose no candidate content."""

    DOCUMENT_TOO_LARGE = "phase_result.document_too_large"
    INVALID_ENCODING = "phase_result.invalid_encoding"
    INVALID_JSON = "phase_result.invalid_json"
    DUPLICATE_KEY = "phase_result.duplicate_key"
    NONFINITE_NUMBER = "phase_result.nonfinite_number"
    NONCANONICAL_JSON = "phase_result.noncanonical_json"
    BOUNDS_EXCEEDED = "phase_result.bounds_exceeded"
    SCHEMA_VIOLATION = "phase_result.schema_violation"
    UNSAFE_TEXT = "phase_result.unsafe_text"
    SEMANTIC_VIOLATION = "phase_result.semantic_violation"
    CREDENTIAL_DETECTED = "phase_result.credential_detected"


class TransientPhaseResultCandidate:
    """An immutable raw candidate whose repr and serialization never expose text."""

    __slots__ = ("__payload",)

    def __init__(self, payload: bytes) -> None:
        if type(payload) is not bytes:
            raise TypeError("phase result candidate must be exact immutable bytes")
        self.__payload = memoryview(payload).tobytes()

    def __repr__(self) -> str:
        return "TransientPhaseResultCandidate(<redacted>)"

    __str__ = __repr__

    def __reduce__(self) -> Never:
        raise TypeError("transient phase result candidates cannot be serialized")

    def __reduce_ex__(self, protocol: SupportsIndex) -> Never:
        del protocol
        raise TypeError("transient phase result candidates cannot be serialized")

    def _copy_for_parser(self) -> bytes:
        """Return an isolated parser copy; callers must not persist or log it."""

        return memoryview(self.__payload).tobytes()


@dataclass(frozen=True)
class PhaseResultContractRef:
    schema_version: str
    schema_digest: str

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str:
            raise TypeError("schema_version must be an exact string")
        if self.schema_version != "boltrig.phase-result.v1":
            raise ValueError("unsupported phase result schema version")
        _require_digest("schema_digest", self.schema_digest)
        if self.schema_digest != PHASE_RESULT_V1_SCHEMA_DIGEST:
            raise ValueError("schema_digest does not match the pinned schema version")


@dataclass(frozen=True)
class UnresolvedEvidenceRef:
    """A worker-declared reference awaiting same-scope registry resolution."""

    evidence_id: str

    def __post_init__(self) -> None:
        _require_identifier("evidence_id", self.evidence_id)


@dataclass(frozen=True)
class UnresolvedProfileRef:
    """A worker-declared profile pin awaiting governed catalogue resolution."""

    name: str
    version: str

    def __post_init__(self) -> None:
        _require_identifier("profile name", self.name)
        if type(self.version) is not str:
            raise TypeError("profile version must be an exact string")
        if len(self.version) > MAX_IDENTIFIER_CHARS:
            raise ValueError("profile version must be a bounded SemVer string")
        if _SEMVER.fullmatch(self.version) is None:
            raise ValueError("profile version must be canonical SemVer")


@dataclass(frozen=True)
class NormalizedPhaseFinding:
    code: str
    severity: PhaseFindingSeverity
    summary_digest: str
    detail_digest: str
    evidence: tuple[UnresolvedEvidenceRef, ...]

    def __post_init__(self) -> None:
        _require_identifier("finding code", self.code)
        _require_exact_enum("finding severity", self.severity, PhaseFindingSeverity)
        _require_digest("finding summary_digest", self.summary_digest)
        _require_digest("finding detail_digest", self.detail_digest)
        _require_refs("finding evidence", self.evidence)


@dataclass(frozen=True)
class NormalizedPhaseBlocker:
    code: str
    summary_digest: str
    detail_digest: str
    evidence: tuple[UnresolvedEvidenceRef, ...]

    def __post_init__(self) -> None:
        _require_identifier("blocker code", self.code)
        _require_digest("blocker summary_digest", self.summary_digest)
        _require_digest("blocker detail_digest", self.detail_digest)
        _require_refs("blocker evidence", self.evidence)


@dataclass(frozen=True)
class NormalizedPhaseHandoff:
    profile: UnresolvedProfileRef
    summary_digest: str
    evidence: tuple[UnresolvedEvidenceRef, ...]

    def __post_init__(self) -> None:
        if type(self.profile) is not UnresolvedProfileRef:
            raise TypeError("handoff profile must be an exact UnresolvedProfileRef")
        _require_digest("handoff summary_digest", self.summary_digest)
        _require_refs("handoff evidence", self.evidence)


@dataclass(frozen=True)
class NormalizedPhaseResult:
    """Credential-screened result containing no worker narrative text."""

    contract: PhaseResultContractRef
    completion: PhaseCompletionStatus
    completion_summary_digest: str
    evidence: tuple[UnresolvedEvidenceRef, ...]
    findings: tuple[NormalizedPhaseFinding, ...]
    blockers: tuple[NormalizedPhaseBlocker, ...]
    handoffs: tuple[NormalizedPhaseHandoff, ...]
    normalized_digest: str

    def __post_init__(self) -> None:
        if type(self.contract) is not PhaseResultContractRef:
            raise TypeError("contract must be an exact PhaseResultContractRef")
        _require_exact_enum("completion", self.completion, PhaseCompletionStatus)
        _require_digest("completion_summary_digest", self.completion_summary_digest)
        _require_tuple("evidence", self.evidence, UnresolvedEvidenceRef, MAX_EVIDENCE_ITEMS)
        _require_tuple("findings", self.findings, NormalizedPhaseFinding, MAX_FINDING_ITEMS)
        _require_tuple("blockers", self.blockers, NormalizedPhaseBlocker, MAX_BLOCKER_ITEMS)
        _require_tuple("handoffs", self.handoffs, NormalizedPhaseHandoff, MAX_HANDOFF_ITEMS)
        _require_digest("normalized_digest", self.normalized_digest)
        evidence_ids = tuple(item.evidence_id for item in self.evidence)
        finding_codes = tuple(item.code for item in self.findings)
        blocker_codes = tuple(item.code for item in self.blockers)
        handoff_profiles = tuple(
            (item.profile.name, item.profile.version) for item in self.handoffs
        )
        _require_sorted_unique("evidence", evidence_ids)
        _require_sorted_unique("finding codes", finding_codes)
        _require_sorted_unique("blocker codes", blocker_codes)
        _require_sorted_unique("handoff profiles", handoff_profiles)
        if set(finding_codes) & set(blocker_codes):
            raise ValueError("finding and blocker codes must be globally unique")
        referenced = {
            ref.evidence_id
            for entries in (self.findings, self.blockers, self.handoffs)
            for entry in entries
            for ref in entry.evidence
        }
        if referenced != set(evidence_ids):
            raise ValueError("normalized result evidence references must resolve exactly")
        if self.completion is PhaseCompletionStatus.COMPLETED and self.blockers:
            raise ValueError("completed phase result cannot contain blockers")
        if self.completion is PhaseCompletionStatus.BLOCKED and not self.blockers:
            raise ValueError("blocked phase result must contain a blocker")


@dataclass(frozen=True)
class PhaseResultRejection:
    code: PhaseResultRejectionCode

    def __post_init__(self) -> None:
        _require_exact_enum("rejection code", self.code, PhaseResultRejectionCode)


PhaseResultParseOutcome = NormalizedPhaseResult | PhaseResultRejection


def _require_identifier(label: str, value: object) -> str:
    if type(value) is not str:
        raise TypeError(f"{label} must be an exact string")
    if _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{label} must be a canonical identifier")
    return value


def _require_digest(label: str, value: object) -> str:
    if type(value) is not str:
        raise TypeError(f"{label} must be an exact string")
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase sha256 digest")
    return value


def _require_exact_enum(label: str, value: object, expected: type[Enum]) -> None:
    if type(value) is not expected:
        raise TypeError(f"{label} must be an exact {expected.__name__}")


def _require_refs(label: str, value: object) -> None:
    _require_tuple(label, value, UnresolvedEvidenceRef, MAX_EVIDENCE_REFS)
    refs = cast(tuple[UnresolvedEvidenceRef, ...], value)
    _require_sorted_unique(label, tuple(item.evidence_id for item in refs))


def _require_sorted_unique(label: str, values: tuple[_SortableKey, ...]) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must be unique")
    if tuple(sorted(values)) != values:
        raise ValueError(f"{label} must be normalized in ascending order")


def _require_tuple(label: str, value: object, expected: type[object], maximum: int) -> None:
    if type(value) is not tuple:
        raise TypeError(f"{label} must be an immutable tuple")
    entries = cast(tuple[object, ...], value)
    if len(entries) > maximum:
        raise ValueError(f"{label} exceeds the collection limit")
    if any(type(entry) is not expected for entry in entries):
        raise TypeError(f"{label} must contain exact {expected.__name__} values")


__all__ = [
    "MAX_BLOCKER_ITEMS",
    "MAX_COMPLETION_SUMMARY_CHARS",
    "MAX_EVIDENCE_ITEMS",
    "MAX_EVIDENCE_REFS",
    "MAX_FINDING_ITEMS",
    "MAX_HANDOFF_ITEMS",
    "MAX_IDENTIFIER_CHARS",
    "MAX_NARRATIVE_CHARS",
    "MAX_PHASE_RESULT_BYTES",
    "MAX_PHASE_RESULT_DEPTH",
    "MAX_PHASE_RESULT_NODES",
    "NormalizedPhaseBlocker",
    "NormalizedPhaseFinding",
    "NormalizedPhaseHandoff",
    "NormalizedPhaseResult",
    "PhaseCompletionStatus",
    "PhaseFindingSeverity",
    "PhaseResultContractRef",
    "PhaseResultParseOutcome",
    "PhaseResultRejection",
    "PhaseResultRejectionCode",
    "PHASE_RESULT_V1_SCHEMA_DIGEST",
    "TransientPhaseResultCandidate",
    "UnresolvedEvidenceRef",
    "UnresolvedProfileRef",
]
