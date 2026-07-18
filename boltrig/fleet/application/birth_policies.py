"""Fail-closed compilation of static profiles into bounded Codex birth policy."""

from __future__ import annotations

from boltrig.fleet.domain.profile_policy import (
    BirthPolicyCompilation,
    BirthPolicyEvidence,
    BirthPolicyRequest,
    CompiledBirthPolicy,
    MAX_COMPILED_REQUIRED_VERBS,
    MAX_SELECTED_SKILLS,
    StaticRoleProfile,
    VersionedSkillManifest,
    selected_catalog_digest,
)
from boltrig.fleet.domain.execution import SandboxPolicy
from boltrig.fleet.domain.profile_policy_values import NativeSubagentLimits, sandbox_within
from boltrig.fleet.ports.profile_catalog import StaticProfileCatalog
from boltrig.models import SkillVersionPin


class BirthPolicyRejected(PermissionError):
    """A catalogue result or requested birth configuration failed closed."""


def _manifest_map(
    manifests: tuple[VersionedSkillManifest, ...],
) -> dict[str, VersionedSkillManifest]:
    if type(manifests) is not tuple:
        raise TypeError("resolved manifests must be an immutable tuple")
    if len(manifests) > MAX_SELECTED_SKILLS:
        raise BirthPolicyRejected("catalogue returned too many skill manifests")
    if any(type(manifest) is not VersionedSkillManifest for manifest in manifests):
        raise TypeError("resolved manifests must be exact VersionedSkillManifest values")
    names = [manifest.name for manifest in manifests]
    if len(names) != len(set(names)):
        raise BirthPolicyRejected("catalogue returned duplicate skill manifests")
    return {manifest.name: manifest for manifest in manifests}


def _verify_selected_catalog(
    request: BirthPolicyRequest,
    profile: StaticRoleProfile,
    manifests: tuple[VersionedSkillManifest, ...],
) -> tuple[VersionedSkillManifest, ...]:
    permitted = {pin.name: pin for pin in profile.permitted_skills}
    for selected in request.selected_skills:
        if permitted.get(selected.name) != selected:
            raise BirthPolicyRejected("selected skill pin is outside the profile catalogue")
    resolved = _manifest_map(manifests)
    if resolved.keys() != {pin.name for pin in request.selected_skills}:
        raise BirthPolicyRejected("catalogue did not resolve the exact selected skill set")
    for selected in request.selected_skills:
        if resolved[selected.name].pin != selected:
            raise BirthPolicyRejected("resolved skill manifest does not match its selected pin")
    return tuple(resolved[pin.name] for pin in request.selected_skills)


def _required_verbs(manifests: tuple[VersionedSkillManifest, ...]) -> tuple[str, ...]:
    verbs = {verb for manifest in manifests for verb in manifest.required_domain_verbs}
    if len(verbs) > MAX_COMPILED_REQUIRED_VERBS:
        raise BirthPolicyRejected("selected skill verb requirements exceed the compiled limit")
    return tuple(sorted(verbs))


def _select_tools(
    request: BirthPolicyRequest,
    profile: StaticRoleProfile,
    manifests: tuple[VersionedSkillManifest, ...],
) -> tuple[str, ...]:
    selected = profile.tools.defaults if request.requested_tools is None else request.requested_tools
    if not set(selected) <= set(profile.tools.ceiling):
        raise BirthPolicyRejected("requested runtime tools exceed the profile ceiling")
    missing = {
        tool
        for manifest in manifests
        for tool in manifest.required_runtime_tools
        if tool not in selected
    }
    if missing:
        raise BirthPolicyRejected(
            "selected skill requirements are not satisfied by enabled runtime tools"
        )
    return selected


def _select_sandbox(
    request: BirthPolicyRequest,
    profile: StaticRoleProfile,
    manifests: tuple[VersionedSkillManifest, ...],
) -> SandboxPolicy:
    selected = (
        profile.default_sandbox
        if request.requested_sandbox is None
        else request.requested_sandbox
    )
    if not sandbox_within(selected, profile.sandbox_ceiling):
        raise BirthPolicyRejected("requested sandbox exceeds the profile ceiling")
    if any(not sandbox_within(manifest.minimum_sandbox, selected) for manifest in manifests):
        raise BirthPolicyRejected(
            "selected skill requirements are not satisfied by the sandbox"
        )
    return selected


def _select_subagent_limits(
    request: BirthPolicyRequest, profile: StaticRoleProfile
) -> NativeSubagentLimits:
    selected = (
        profile.native_subagents.defaults
        if request.requested_native_subagents is None
        else request.requested_native_subagents
    )
    if not selected.within(profile.native_subagents.ceiling):
        raise BirthPolicyRejected("requested native subagents exceed the profile ceiling")
    return selected


def compile_birth_policy(
    request: BirthPolicyRequest,
    profile: StaticRoleProfile,
    manifests: tuple[VersionedSkillManifest, ...],
) -> BirthPolicyCompilation:
    """Compile exact policy inputs without evaluating or manufacturing authority."""

    if type(request) is not BirthPolicyRequest:
        raise TypeError("request must be exact BirthPolicyRequest")
    if type(profile) is not StaticRoleProfile:
        raise TypeError("profile must be exact StaticRoleProfile")
    if profile.pin != request.profile:
        raise BirthPolicyRejected("resolved profile does not match the requested pin")
    selected_manifests = _verify_selected_catalog(request, profile, manifests)
    policy = CompiledBirthPolicy(
        profile=profile.pin,
        instructions=profile.instructions,
        model=profile.model,
        enabled_tools=_select_tools(request, profile, selected_manifests),
        tool_ceiling=profile.tools.ceiling,
        sandbox=_select_sandbox(request, profile, selected_manifests),
        sandbox_ceiling=profile.sandbox_ceiling,
        native_subagents=_select_subagent_limits(request, profile),
        native_subagent_ceiling=profile.native_subagents.ceiling,
        selected_skills=tuple(manifest.pin for manifest in selected_manifests),
        required_domain_verbs=_required_verbs(selected_manifests),
    )
    evidence = BirthPolicyEvidence(
        request_digest=request.digest(),
        profile_digest=profile.definition_digest(),
        selected_catalog_digest=selected_catalog_digest(selected_manifests),
        compiled_policy_digest=policy.digest(),
    )
    return BirthPolicyCompilation(policy, evidence)


class BirthPolicyCompiler:
    """Resolve pins through a port, then verify and compile them fail closed."""

    def __init__(self, catalog: StaticProfileCatalog) -> None:
        self._catalog = catalog

    async def compile(self, request: BirthPolicyRequest) -> BirthPolicyCompilation:
        if type(request) is not BirthPolicyRequest:
            raise TypeError("request must be exact BirthPolicyRequest")
        profile = await self._catalog.resolve_profile(request.profile)
        manifests = await self._catalog.resolve_skills(request.selected_skills)
        return compile_birth_policy(request, profile, manifests)


def selected_skill_pins(
    manifests: tuple[VersionedSkillManifest, ...],
) -> tuple[SkillVersionPin, ...]:
    """Return canonical pins for a caller constructing a governed request."""

    resolved = _manifest_map(manifests)
    return tuple(resolved[name].pin for name in sorted(resolved))


__all__ = [
    "BirthPolicyCompiler",
    "BirthPolicyRejected",
    "compile_birth_policy",
    "selected_skill_pins",
]
