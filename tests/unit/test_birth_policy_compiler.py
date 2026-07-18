from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError, replace

import pytest

from boltrig.fleet.application import (
    BirthPolicyCompiler as ExportedBirthPolicyCompiler,
    compile_birth_policy as exported_compile_birth_policy,
)
from boltrig.fleet.application.birth_policies import (
    BirthPolicyCompiler,
    BirthPolicyRejected,
    compile_birth_policy,
    selected_skill_pins,
)
from boltrig.fleet.domain.execution import SandboxPolicy
from boltrig.fleet.domain.profile_policy import (
    BirthPolicyRequest,
    StaticRoleProfile,
    VersionedSkillManifest,
)
from boltrig.fleet.domain.profile_policy_values import (
    DigestPinnedContent,
    ExactModelPolicy,
    NativeSubagentLimits,
    NativeSubagentPolicy,
    ReasoningEffort,
    RuntimeToolPolicy,
)
from boltrig.models import ProfileVersionPin, SkillVersionPin
from boltrig.fleet.ports import StaticProfileCatalog as ExportedStaticProfileCatalog
from boltrig.fleet.ports.profile_catalog import StaticProfileCatalog


def _digest(character: str) -> str:
    return f"sha256:{hashlib.sha256(character.encode()).hexdigest()}"


def _skill(
    name: str,
    version: str,
    verbs: tuple[str, ...],
    *,
    tools: tuple[str, ...] = ("mcp.opbox",),
    sandbox: SandboxPolicy = SandboxPolicy.READ_ONLY,
) -> VersionedSkillManifest:
    return VersionedSkillManifest(
        name,
        version,
        DigestPinnedContent(f"skills/{name}/{version}/SKILL.md", _digest(name[0])),
        _digest(f"directory:{name}:{version}"),
        verbs,
        tools,
        sandbox,
    )


RESEARCH = _skill("case-research", "1.3.0", ("case.read", "case.search"))
WRITE = _skill(
    "contract-write",
    "4.0.1",
    ("contract.read", "contract.update"),
    tools=("filesystem.write", "mcp.opbox"),
    sandbox=SandboxPolicy.WORKSPACE_WRITE,
)


def _profile(*skills: VersionedSkillManifest) -> StaticRoleProfile:
    return StaticRoleProfile(
        "head_of_legal",
        "2.1.0",
        DigestPinnedContent("profiles/head_of_legal/2.1.0/instructions.md", _digest("p")),
        ExactModelPolicy("gpt-5.4-codex", ReasoningEffort.HIGH),
        RuntimeToolPolicy(
            defaults=("filesystem.read", "mcp.opbox"),
            ceiling=(
                "filesystem.read",
                "filesystem.write",
                "mcp.opbox",
                "shell.exec",
            ),
        ),
        SandboxPolicy.READ_ONLY,
        SandboxPolicy.WORKSPACE_WRITE,
        tuple(skill.pin for skill in skills),
        NativeSubagentPolicy(
            NativeSubagentLimits(1, 2, 1),
            NativeSubagentLimits(4, 12, 2),
        ),
    )


def test_application_and_port_packages_explicitly_reexport_birth_contracts() -> None:
    assert ExportedBirthPolicyCompiler is BirthPolicyCompiler
    assert exported_compile_birth_policy is compile_birth_policy
    assert ExportedStaticProfileCatalog is StaticProfileCatalog


def test_compilation_is_deterministic_pinned_and_auditable() -> None:
    profile = _profile(RESEARCH, WRITE)
    first_request = BirthPolicyRequest(
        profile.pin,
        (WRITE.pin, RESEARCH.pin),
        requested_tools=("mcp.opbox", "filesystem.write", "filesystem.read"),
        requested_sandbox=SandboxPolicy.WORKSPACE_WRITE,
        requested_native_subagents=NativeSubagentLimits(2, 6, 1),
    )
    second_request = BirthPolicyRequest(
        profile.pin,
        (RESEARCH.pin, WRITE.pin),
        requested_tools=("filesystem.read", "filesystem.write", "mcp.opbox"),
        requested_sandbox=SandboxPolicy.WORKSPACE_WRITE,
        requested_native_subagents=NativeSubagentLimits(2, 6, 1),
    )

    first = compile_birth_policy(first_request, profile, (WRITE, RESEARCH))
    second = compile_birth_policy(second_request, profile, (RESEARCH, WRITE))

    assert first == second
    assert first.policy.profile == profile.pin
    assert first.policy.selected_skills == (RESEARCH.pin, WRITE.pin)
    assert first.policy.required_domain_verbs == (
        "case.read",
        "case.search",
        "contract.read",
        "contract.update",
    )
    assert first.evidence.profile_digest == profile.pin.digest
    assert first.evidence.request_digest == first_request.digest()
    assert first.evidence.compiled_policy_digest == first.policy.digest()
    assert first.evidence.compiler_version == "1.0.0"
    with pytest.raises(FrozenInstanceError):
        first.policy.enabled_tools = ()  # type: ignore[misc]


def test_skill_selection_never_auto_enables_tools_or_escalates_sandbox() -> None:
    profile = _profile(WRITE)
    default_request = BirthPolicyRequest(profile.pin, (WRITE.pin,))

    with pytest.raises(BirthPolicyRejected, match="runtime tools"):
        compile_birth_policy(default_request, profile, (WRITE,))

    tools_only = replace(
        default_request,
        requested_tools=("filesystem.read", "filesystem.write", "mcp.opbox"),
    )
    with pytest.raises(BirthPolicyRejected, match="sandbox"):
        compile_birth_policy(tools_only, profile, (WRITE,))

    explicit = replace(tools_only, requested_sandbox=SandboxPolicy.WORKSPACE_WRITE)
    compiled = compile_birth_policy(explicit, profile, (WRITE,))
    assert compiled.policy.enabled_tools == (
        "filesystem.read",
        "filesystem.write",
        "mcp.opbox",
    )
    assert compiled.policy.sandbox is SandboxPolicy.WORKSPACE_WRITE
    assert not hasattr(compiled.policy, "grants")
    assert not hasattr(compiled.policy, "authority")


def test_requests_cannot_exceed_profile_tool_sandbox_or_subagent_ceilings() -> None:
    profile = _profile(RESEARCH)
    with pytest.raises(BirthPolicyRejected, match="tools exceed"):
        compile_birth_policy(
            BirthPolicyRequest(profile.pin, (RESEARCH.pin,), ("network.open",)),
            profile,
            (RESEARCH,),
        )

    read_only = replace(profile, sandbox_ceiling=SandboxPolicy.READ_ONLY)
    with pytest.raises(BirthPolicyRejected, match="sandbox exceeds"):
        compile_birth_policy(
            BirthPolicyRequest(
                read_only.pin,
                (RESEARCH.pin,),
                requested_sandbox=SandboxPolicy.WORKSPACE_WRITE,
            ),
            read_only,
            (RESEARCH,),
        )

    with pytest.raises(BirthPolicyRejected, match="subagents exceed"):
        compile_birth_policy(
            BirthPolicyRequest(
                profile.pin,
                (RESEARCH.pin,),
                requested_native_subagents=NativeSubagentLimits(5, 12, 2),
            ),
            profile,
            (RESEARCH,),
        )


@pytest.mark.parametrize("variant", ["unknown", "version", "digest"])
def test_selected_skill_pin_must_match_profile_catalogue_exactly(variant: str) -> None:
    profile = _profile(RESEARCH)
    selected = {
        "unknown": SkillVersionPin("other-skill", "1.3.0", RESEARCH.pin.digest),
        "version": SkillVersionPin(RESEARCH.name, "9.9.9", RESEARCH.pin.digest),
        "digest": SkillVersionPin(RESEARCH.name, RESEARCH.version, _digest("f")),
    }[variant]
    request = BirthPolicyRequest(profile.pin, (selected,))

    with pytest.raises(BirthPolicyRejected, match="outside"):
        compile_birth_policy(request, profile, (RESEARCH,))


def test_profile_and_manifest_resolution_must_match_exact_requested_pins() -> None:
    profile = _profile(RESEARCH)
    request = BirthPolicyRequest(profile.pin, (RESEARCH.pin,))
    other_profile = replace(
        profile,
        version="2.2.0",
        instructions=DigestPinnedContent(
            "profiles/head_of_legal/2.2.0/instructions.md", _digest("p")
        ),
    )
    drifted = replace(RESEARCH, required_domain_verbs=("admin.delete",))

    with pytest.raises(BirthPolicyRejected, match="profile"):
        compile_birth_policy(request, other_profile, (RESEARCH,))
    with pytest.raises(BirthPolicyRejected, match="manifest"):
        compile_birth_policy(request, profile, (drifted,))
    with pytest.raises(BirthPolicyRejected, match="exact selected"):
        compile_birth_policy(request, profile, ())
    with pytest.raises(BirthPolicyRejected, match="exact selected"):
        compile_birth_policy(request, profile, (RESEARCH, WRITE))
    with pytest.raises(BirthPolicyRejected, match="duplicate"):
        compile_birth_policy(request, profile, (RESEARCH, RESEARCH))


def test_compiled_requirement_union_is_bounded() -> None:
    first_verbs = tuple(f"first.v{index}" for index in range(128))
    second_verbs = tuple(f"second.v{index}" for index in range(128))
    third_verbs = ("third.overflow",)
    first = _skill("first-skill", "1.0.0", first_verbs)
    second = _skill("second-skill", "1.0.0", second_verbs)
    third = _skill("third-skill", "1.0.0", third_verbs)
    profile = _profile(first, second, third)
    request = BirthPolicyRequest(profile.pin, selected_skill_pins((first, second, third)))

    with pytest.raises(BirthPolicyRejected, match="verb requirements"):
        compile_birth_policy(request, profile, (first, second, third))


class _Catalog:
    def __init__(
        self,
        profile: StaticRoleProfile,
        manifests: tuple[VersionedSkillManifest, ...],
    ) -> None:
        self.profile = profile
        self.manifests = manifests
        self.profile_pin: ProfileVersionPin | None = None
        self.skill_pins: tuple[SkillVersionPin, ...] | None = None

    async def resolve_profile(self, pin: ProfileVersionPin) -> StaticRoleProfile:
        self.profile_pin = pin
        return self.profile

    async def resolve_skills(
        self, pins: tuple[SkillVersionPin, ...]
    ) -> tuple[VersionedSkillManifest, ...]:
        self.skill_pins = pins
        return self.manifests


@pytest.mark.asyncio
async def test_application_compiler_resolves_exact_pins_then_revalidates_catalogue() -> None:
    profile = _profile(RESEARCH)
    request = BirthPolicyRequest(profile.pin, (RESEARCH.pin,))
    catalog = _Catalog(profile, (RESEARCH,))

    result = await BirthPolicyCompiler(catalog).compile(request)

    assert result.policy.selected_skills == (RESEARCH.pin,)
    assert catalog.profile_pin == request.profile
    assert catalog.skill_pins == request.selected_skills

    catalog.manifests = (replace(RESEARCH, required_domain_verbs=("admin.delete",)),)
    with pytest.raises(BirthPolicyRejected, match="manifest"):
        await BirthPolicyCompiler(catalog).compile(request)
