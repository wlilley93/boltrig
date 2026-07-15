"""Adapt bounded Codex skills/list data into the pure attestation boundary."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from boltrig.fleet.domain.skill_attestation import (
    MAX_SKILLS,
    ExpectedSkill,
    ObservedSkill,
    SkillAttestation,
    SkillAttestationError,
    SkillAttestationPlan,
    SkillDiscoveryReport,
    SkillScope,
    absolute_posix_path,
    attest_skill_discovery,
    skill_name,
)

from .bounded_filesystem import (
    ArtifactProjectionError,
    FilesystemLimits,
    capture_directory,
)


def force_reload_params(plan: SkillAttestationPlan) -> dict[str, object]:
    """Return the only discovery request shape accepted before thread/start."""

    if not isinstance(plan, SkillAttestationPlan):
        raise TypeError("plan must be a SkillAttestationPlan")
    return {"cwds": [plan.workspace_path], "forceReload": True}


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise SkillAttestationError("Codex skill discovery response is malformed")
    return value


def _string(value: object, *, path: bool = False, name: bool = False) -> str:
    if not isinstance(value, str):
        raise SkillAttestationError("Codex skill discovery response is malformed")
    try:
        if path:
            return absolute_posix_path(value)
        if name:
            return skill_name(value)
    except ValueError as exc:
        raise SkillAttestationError("Codex skill discovery response is malformed") from exc
    return value


def _scope(value: object) -> SkillScope:
    if not isinstance(value, str):
        raise SkillAttestationError("Codex skill discovery response is malformed")
    try:
        return SkillScope(value)
    except ValueError as exc:
        raise SkillAttestationError("Codex skill discovery response is malformed") from exc


def _artifact_digests(
    expected: ExpectedSkill,
    limits: FilesystemLimits,
) -> tuple[str, str]:
    try:
        capture = capture_directory(
            Path(expected.manifest_path).parent,
            limits,
            reject_controls=True,
        )
        manifest = capture.file("SKILL.md")
    except ArtifactProjectionError as exc:
        raise SkillAttestationError("Codex skill discovery failed artifact verification") from exc
    return capture.accounting.digest, f"sha256:{manifest.content_digest}"


def _observed(
    value: object,
    expected: Mapping[str, ExpectedSkill],
    limits: FilesystemLimits,
) -> ObservedSkill:
    item = _mapping(value)
    name = _string(item.get("name"), name=True)
    manifest_path = _string(item.get("path"), path=True)
    scope = _scope(item.get("scope"))
    enabled = item.get("enabled")
    if type(enabled) is not bool:
        raise SkillAttestationError("Codex skill discovery response is malformed")
    directory_digest: str | None = None
    manifest_digest: str | None = None
    if enabled:
        wanted = expected.get(name)
        if wanted is None or wanted.manifest_path != manifest_path or wanted.scope is not scope:
            raise SkillAttestationError("Codex enabled an unselected skill")
        directory_digest, manifest_digest = _artifact_digests(wanted, limits)
    return ObservedSkill(
        name=name,
        manifest_path=manifest_path,
        scope=scope,
        enabled=enabled,
        directory_digest=directory_digest,
        manifest_digest=manifest_digest,
    )


def parse_skills_list(
    payload: Mapping[str, object],
    plan: SkillAttestationPlan,
    limits: FilesystemLimits = FilesystemLimits(),
) -> SkillDiscoveryReport:
    """Parse exactly one bounded cwd entry and locally digest enabled selections."""

    root = _mapping(payload)
    data = root.get("data")
    if not isinstance(data, list) or len(data) != 1:
        raise SkillAttestationError("Codex skill discovery response is malformed")
    entry = _mapping(data[0])
    cwd = _string(entry.get("cwd"), path=True)
    skills = entry.get("skills")
    errors = entry.get("errors")
    if not isinstance(skills, list) or len(skills) > MAX_SKILLS:
        raise SkillAttestationError("Codex skill discovery response is malformed")
    if not isinstance(errors, list) or len(errors) > MAX_SKILLS:
        raise SkillAttestationError("Codex skill discovery response is malformed")
    expected = {item.name: item for item in plan.selected}
    observed = tuple(_observed(item, expected, limits) for item in skills)
    return SkillDiscoveryReport(cwd=cwd, skills=observed, error_count=len(errors))


def attest_skills_list(
    payload: Mapping[str, object],
    plan: SkillAttestationPlan,
    limits: FilesystemLimits = FilesystemLimits(),
) -> SkillAttestation:
    """Run the complete pre-thread, force-reload response attestation."""

    report = parse_skills_list(payload, plan, limits)
    return attest_skill_discovery(plan, report)


__all__ = [
    "attest_skills_list",
    "force_reload_params",
    "parse_skills_list",
]
