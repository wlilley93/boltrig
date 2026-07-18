"""Fail-closed attestation for Codex skill discovery before a thread starts."""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from dataclasses import dataclass
from enum import Enum

MAX_SKILLS = 128
MAX_NAME_LENGTH = 128
MAX_PATH_LENGTH = 4096
_NAME_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,126}[A-Za-z0-9])?\Z")


class SkillAttestationError(RuntimeError):
    """Discovery did not exactly match Boltrig's selected skill allowlist."""


class SkillScope(str, Enum):
    """Skill scopes emitted by Codex App Server 0.144.3."""

    USER = "user"
    REPO = "repo"
    SYSTEM = "system"
    ADMIN = "admin"


def skill_name(value: str) -> str:
    """Return a bounded skill name safe for an exact directory component."""

    if not isinstance(value, str) or not _NAME_PATTERN.fullmatch(value):
        raise ValueError("skill name must be a bounded safe identifier")
    if len(value) > MAX_NAME_LENGTH:
        raise ValueError("skill name exceeds the bounded length")
    return value


def absolute_posix_path(value: str) -> str:
    """Return an absolute POSIX path only when its spelling is already canonical."""

    if not isinstance(value, str) or not value or len(value) > MAX_PATH_LENGTH:
        raise ValueError("path must be a bounded absolute POSIX path")
    if "\x00" in value or not value.startswith("/"):
        raise ValueError("path must be a bounded absolute POSIX path")
    if posixpath.normpath(value) != value or "//" in value:
        raise ValueError("path must be normalized")
    return value


def sha256_digest(value: str) -> str:
    """Validate the audit digest representation used by this boundary."""

    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise ValueError("digest must use the sha256 prefix")
    hexadecimal = value.removeprefix("sha256:")
    if re.fullmatch(r"[0-9a-f]{64}", hexadecimal) is None:
        raise ValueError("digest must contain lowercase SHA-256 hexadecimal")
    return value


@dataclass(frozen=True, order=True)
class ExpectedSkill:
    """One digest-pinned skill Boltrig materialized for this Codex cell."""

    name: str
    manifest_path: str
    scope: SkillScope
    directory_digest: str
    manifest_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", skill_name(self.name))
        object.__setattr__(self, "manifest_path", absolute_posix_path(self.manifest_path))
        if not isinstance(self.scope, SkillScope):
            raise TypeError("skill scope must be a SkillScope")
        object.__setattr__(self, "directory_digest", sha256_digest(self.directory_digest))
        object.__setattr__(self, "manifest_digest", sha256_digest(self.manifest_digest))
        if not self.manifest_path.endswith("/SKILL.md"):
            raise ValueError("selected skill manifest path must end in SKILL.md")


@dataclass(frozen=True, order=True)
class ObservedSkill:
    """Bounded discovery metadata plus locally recomputed artifact digests."""

    name: str
    manifest_path: str
    scope: SkillScope
    enabled: bool
    directory_digest: str | None = None
    manifest_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", skill_name(self.name))
        object.__setattr__(self, "manifest_path", absolute_posix_path(self.manifest_path))
        if not isinstance(self.scope, SkillScope):
            raise TypeError("skill scope must be a SkillScope")
        if type(self.enabled) is not bool:
            raise TypeError("enabled must be a boolean")
        if self.enabled and (self.directory_digest is None or self.manifest_digest is None):
            raise ValueError("enabled skills require recomputed artifact digests")
        if self.directory_digest is not None:
            object.__setattr__(self, "directory_digest", sha256_digest(self.directory_digest))
        if self.manifest_digest is not None:
            object.__setattr__(self, "manifest_digest", sha256_digest(self.manifest_digest))


@dataclass(frozen=True)
class SkillAttestationPlan:
    """The exact cwd and allowlist a force-reloaded discovery must satisfy."""

    workspace_path: str
    selected: tuple[ExpectedSkill, ...]
    generation: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_path", absolute_posix_path(self.workspace_path))
        if not isinstance(self.selected, tuple) or len(self.selected) > MAX_SKILLS:
            raise ValueError(f"at most {MAX_SKILLS} selected skills are permitted")
        if any(not isinstance(item, ExpectedSkill) for item in self.selected):
            raise TypeError("selected entries must be ExpectedSkill values")
        names = [item.name for item in self.selected]
        paths = [item.manifest_path for item in self.selected]
        if len(names) != len(set(names)) or len(paths) != len(set(paths)):
            raise ValueError("selected skill names and paths must be unique")
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError("attestation plan generation must be non-negative")

    def digest(self) -> str:
        """Bind a receipt to this exact allowlist, cwd, and invalidation generation."""

        document = {
            "cwd": self.workspace_path,
            "generation": self.generation,
            "selected": [_expected_document(item) for item in sorted(self.selected)],
        }
        return _document_digest(document)


@dataclass(frozen=True)
class SkillDiscoveryReport:
    """One bounded skills/list entry after local digest enrichment."""

    cwd: str
    skills: tuple[ObservedSkill, ...]
    error_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "cwd", absolute_posix_path(self.cwd))
        if not isinstance(self.skills, tuple) or len(self.skills) > MAX_SKILLS:
            raise ValueError(f"discovery permits at most {MAX_SKILLS} skill entries")
        if any(not isinstance(item, ObservedSkill) for item in self.skills):
            raise TypeError("discovery entries must be ObservedSkill values")
        if type(self.error_count) is not int or self.error_count < 0 or self.error_count > MAX_SKILLS:
            raise ValueError("discovery error count is invalid")


@dataclass(frozen=True)
class SkillAttestation:
    """Safe audit receipt proving one exact discovery result was accepted."""

    digest: str
    plan_digest: str
    generation: int
    workspace_path: str
    selected_names: tuple[str, ...]
    observed_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "digest", sha256_digest(self.digest))
        object.__setattr__(self, "plan_digest", sha256_digest(self.plan_digest))
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError("attestation generation must be non-negative")
        object.__setattr__(self, "workspace_path", absolute_posix_path(self.workspace_path))
        if tuple(sorted(self.selected_names)) != self.selected_names:
            raise ValueError("attested skill names must be sorted")
        if len(set(self.selected_names)) != len(self.selected_names):
            raise ValueError("attested skill names must be unique")
        for name in self.selected_names:
            skill_name(name)
        if type(self.observed_count) is not int or not 0 <= self.observed_count <= MAX_SKILLS:
            raise ValueError("observed skill count is invalid")


def attest_skill_discovery(
    plan: SkillAttestationPlan,
    report: SkillDiscoveryReport,
) -> SkillAttestation:
    """Fail closed unless the enabled discovery set exactly equals the allowlist."""

    if report.cwd != plan.workspace_path or report.error_count:
        raise SkillAttestationError("Codex skill discovery failed attestation")
    names = [item.name for item in report.skills]
    paths = [item.manifest_path for item in report.skills]
    if len(names) != len(set(names)) or len(paths) != len(set(paths)):
        raise SkillAttestationError("Codex skill discovery failed attestation")
    enabled = {item.name: item for item in report.skills if item.enabled}
    expected = {item.name: item for item in plan.selected}
    if enabled.keys() != expected.keys():
        raise SkillAttestationError("Codex skill discovery failed attestation")
    for name, wanted in expected.items():
        found = enabled[name]
        if (
            found.manifest_path != wanted.manifest_path
            or found.scope is not wanted.scope
            or found.directory_digest != wanted.directory_digest
            or found.manifest_digest != wanted.manifest_digest
        ):
            raise SkillAttestationError("Codex skill discovery failed attestation")
    return _receipt(plan, report)


def _receipt(plan: SkillAttestationPlan, report: SkillDiscoveryReport) -> SkillAttestation:
    selected = sorted(plan.selected, key=lambda item: item.name)
    observed = sorted(report.skills, key=lambda item: (item.name, item.manifest_path))
    document = {
        "cwd": plan.workspace_path,
        "generation": plan.generation,
        "observed": [
            {
                "digest": item.directory_digest,
                "enabled": item.enabled,
                "manifest_digest": item.manifest_digest,
                "name": item.name,
                "path": item.manifest_path,
                "scope": item.scope.value,
            }
            for item in observed
        ],
        "selected": [
            _expected_document(item)
            for item in selected
        ],
    }
    return SkillAttestation(
        digest=_document_digest(document),
        plan_digest=plan.digest(),
        generation=plan.generation,
        workspace_path=plan.workspace_path,
        selected_names=tuple(item.name for item in selected),
        observed_count=len(report.skills),
    )


def _expected_document(item: ExpectedSkill) -> dict[str, object]:
    return {
        "digest": item.directory_digest,
        "manifest_digest": item.manifest_digest,
        "name": item.name,
        "path": item.manifest_path,
        "scope": item.scope.value,
    }


def _document_digest(document: dict[str, object]) -> str:
    encoded = json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


@dataclass(frozen=True)
class SkillAttestationState:
    """Immutable invalidation gate; skills/changed makes current() fail closed."""

    generation: int = 0
    attested_generation: int | None = None
    attestation: SkillAttestation | None = None

    def __post_init__(self) -> None:
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError("attestation generation must be non-negative")
        if (self.attested_generation is None) != (self.attestation is None):
            raise ValueError("attestation value and generation must be set together")
        if self.attested_generation is not None and self.attested_generation != self.generation:
            raise ValueError("stale attestation cannot be installed")

    def accept(
        self,
        attestation: SkillAttestation,
        plan: SkillAttestationPlan,
    ) -> SkillAttestationState:
        if not isinstance(attestation, SkillAttestation):
            raise TypeError("attestation must be a SkillAttestation")
        if not isinstance(plan, SkillAttestationPlan):
            raise TypeError("plan must be a SkillAttestationPlan")
        if (
            plan.generation != self.generation
            or attestation.generation != self.generation
            or attestation.plan_digest != plan.digest()
        ):
            raise SkillAttestationError("Codex skill attestation is stale or belongs to another plan")
        return SkillAttestationState(self.generation, self.generation, attestation)

    def invalidate(self) -> SkillAttestationState:
        return SkillAttestationState(generation=self.generation + 1)

    def current(self) -> SkillAttestation:
        if self.attestation is None or self.attested_generation != self.generation:
            raise SkillAttestationError("Codex skill discovery is not currently attested")
        return self.attestation


__all__ = [
    "ExpectedSkill",
    "MAX_SKILLS",
    "ObservedSkill",
    "SkillAttestation",
    "SkillAttestationError",
    "SkillAttestationPlan",
    "SkillAttestationState",
    "SkillDiscoveryReport",
    "SkillScope",
    "absolute_posix_path",
    "attest_skill_discovery",
    "sha256_digest",
    "skill_name",
]
