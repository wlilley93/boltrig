from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError, replace

import pytest

from boltrig.fleet.domain.execution import SandboxPolicy
from boltrig.fleet.domain import (
    BirthPolicyRequest as ExportedBirthPolicyRequest,
    StaticRoleProfile as ExportedStaticRoleProfile,
    VersionedSkillManifest as ExportedVersionedSkillManifest,
)
from boltrig.fleet.domain.profile_policy import (
    BirthPolicyRequest,
    StaticRoleProfile,
    VersionedSkillManifest,
)
from boltrig.fleet.domain.profile_policy_values import (
    DigestPinnedContent,
    ExactModelPolicy,
    MAX_NATIVE_SUBAGENTS_CONCURRENT,
    NativeSubagentLimits,
    NativeSubagentPolicy,
    ReasoningEffort,
    RuntimeToolPolicy,
)
from boltrig.models import ProfileVersionPin, SkillVersionPin


def _digest(character: str) -> str:
    return f"sha256:{hashlib.sha256(character.encode()).hexdigest()}"


def _skill(
    name: str = "case-research",
    version: str = "1.3.0",
    *,
    verbs: tuple[str, ...] = ("case.read",),
    tools: tuple[str, ...] = ("mcp.opbox",),
    sandbox: SandboxPolicy = SandboxPolicy.READ_ONLY,
) -> VersionedSkillManifest:
    return VersionedSkillManifest(
        name=name,
        version=version,
        artifact=DigestPinnedContent(
            f"skills/{name}/{version}/SKILL.md",
            _digest("a"),
        ),
        artifact_directory_digest=_digest(f"directory:{name}:{version}"),
        required_domain_verbs=verbs,
        required_runtime_tools=tools,
        minimum_sandbox=sandbox,
    )


def _profile(*skills: VersionedSkillManifest) -> StaticRoleProfile:
    return StaticRoleProfile(
        name="head_of_legal",
        version="2.1.0",
        instructions=DigestPinnedContent(
            "profiles/head_of_legal/2.1.0/instructions.md",
            _digest("b"),
        ),
        model=ExactModelPolicy("gpt-5.4-codex", ReasoningEffort.HIGH),
        tools=RuntimeToolPolicy(
            defaults=("filesystem.read", "mcp.opbox"),
            ceiling=("filesystem.read", "mcp.opbox", "shell.exec"),
        ),
        default_sandbox=SandboxPolicy.READ_ONLY,
        sandbox_ceiling=SandboxPolicy.WORKSPACE_WRITE,
        permitted_skills=tuple(skill.pin for skill in skills),
        native_subagents=NativeSubagentPolicy(
            defaults=NativeSubagentLimits(2, 4, 1),
            ceiling=NativeSubagentLimits(4, 12, 2),
        ),
    )


def test_domain_package_explicitly_reexports_profile_contracts() -> None:
    assert ExportedBirthPolicyRequest is BirthPolicyRequest
    assert ExportedStaticRoleProfile is StaticRoleProfile
    assert ExportedVersionedSkillManifest is VersionedSkillManifest


def test_static_profile_and_skill_pins_are_computed_canonical_and_immutable() -> None:
    research = _skill()
    review = _skill("contract-review", "4.0.1", verbs=("contract.read",))
    first = _profile(research, review)
    second = _profile(review, research)

    assert first == second
    assert first.pin == second.pin
    assert first.permitted_skills == (research.pin, review.pin)
    assert research.pin.digest == research.definition_digest()
    assert first.pin.digest == first.definition_digest()
    assert first.model.model_id == "gpt-5.4-codex"
    assert first.native_subagents.ceiling.max_total == 12
    with pytest.raises(FrozenInstanceError):
        first.name = "attacker"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        research.required_domain_verbs = ("admin.delete",)  # type: ignore[misc]


def test_skill_pin_binds_manifest_and_entire_artifact_directory() -> None:
    skill = _skill()

    changed_manifest = replace(
        skill,
        artifact=DigestPinnedContent(skill.artifact.reference, _digest("changed-manifest")),
    )
    changed_directory = replace(skill, artifact_directory_digest=_digest("changed-directory"))

    assert changed_manifest.pin != skill.pin
    assert changed_directory.pin != skill.pin
    with pytest.raises(ValueError, match="directory digest"):
        replace(skill, artifact_directory_digest="sha256:BAD")


@pytest.mark.parametrize(
    "version",
    ["", "1", "1.0", "v1.0.0", "latest", "main", "1.0.x", "1.0.0/latest"],
)
def test_profiles_and_skills_reject_mutable_or_unversioned_versions(version: str) -> None:
    with pytest.raises(ValueError, match="semantic version"):
        VersionedSkillManifest(
            name="case-research",
            version=version,
            artifact=DigestPinnedContent(
                "skills/case-research/1.3.0/SKILL.md", _digest("a")
            ),
            artifact_directory_digest=_digest("directory"),
        )

    valid = _profile(_skill())
    with pytest.raises(ValueError):
        BirthPolicyRequest(
            ProfileVersionPin(valid.name, version, valid.pin.digest),
        )


def test_exact_semver_build_metadata_is_supported_by_catalogue_references() -> None:
    skill = _skill(version="1.3.0-rc.1+build.7")

    assert skill.version == "1.3.0-rc.1+build.7"
    assert skill.artifact.reference == "skills/case-research/1.3.0-rc.1+build.7/SKILL.md"


@pytest.mark.parametrize(
    "reference",
    [
        "/etc/passwd",
        "../instructions.md",
        "profiles/../instructions.md",
        "profiles//instructions.md",
        "profiles\\instructions.md",
        "profiles/instructions.md\x00ignored",
        "profiles/instructions.md\nignored",
    ],
)
def test_content_references_reject_host_paths_traversal_and_controls(reference: str) -> None:
    with pytest.raises(ValueError, match="normalized relative path"):
        DigestPinnedContent(reference, _digest("c"))


@pytest.mark.parametrize(
    "verb",
    ["*", "case.*", "case.read*", "case/read", "case.read\nadmin.delete", "Case.read"],
)
def test_skill_requirements_reject_wildcards_paths_and_controls(verb: str) -> None:
    with pytest.raises(ValueError, match="concrete canonical"):
        _skill(verbs=(verb,))


def test_skill_requirements_and_profile_catalogues_reject_duplicates() -> None:
    with pytest.raises(ValueError, match="required verbs must be unique"):
        _skill(verbs=("case.read", "case.read"))
    with pytest.raises(ValueError, match="runtime tools must be unique"):
        _skill(tools=("mcp.opbox", "mcp.opbox"))

    skill = _skill()
    with pytest.raises(ValueError, match="unique by skill name"):
        _profile(skill, skill)

    with pytest.raises(ValueError, match="unique by skill name"):
        BirthPolicyRequest(
            _profile(skill).pin,
            (skill.pin, SkillVersionPin(skill.name, "9.9.9", _digest("f"))),
        )


@pytest.mark.parametrize(
    "model_id",
    ["latest", "gpt-latest", "auto", "gpt/default", "gpt-5.4\nadmin"],
)
def test_exact_model_policy_rejects_aliases_paths_and_controls(model_id: str) -> None:
    with pytest.raises(ValueError):
        ExactModelPolicy(model_id, ReasoningEffort.HIGH)


def test_exact_model_policy_accepts_nested_bifrost_ids_through_160_chars() -> None:
    nested = "openrouter/vendor/team/" + "m" * 137
    assert len(nested) == 160
    assert ExactModelPolicy(nested, ReasoningEffort.HIGH).model_id == nested


def test_exact_model_policy_accepts_provider_scoped_bifrost_ids() -> None:
    model_id = "cloudflare/@cf/meta/llama-3.1-8b-instruct"
    assert ExactModelPolicy(model_id, ReasoningEffort.HIGH).model_id == model_id


def test_tool_sandbox_and_native_subagent_defaults_must_stay_within_ceilings() -> None:
    with pytest.raises(ValueError, match="runtime tools"):
        RuntimeToolPolicy(defaults=("shell.exec",), ceiling=("filesystem.read",))
    with pytest.raises(ValueError, match="default sandbox"):
        StaticRoleProfile(
            name="writer",
            version="1.0.0",
            instructions=DigestPinnedContent(
                "profiles/writer/1.0.0/instructions.md", _digest("1")
            ),
            model=ExactModelPolicy("gpt-5.4-codex", ReasoningEffort.MEDIUM),
            tools=RuntimeToolPolicy(),
            default_sandbox=SandboxPolicy.WORKSPACE_WRITE,
            sandbox_ceiling=SandboxPolicy.READ_ONLY,
        )
    with pytest.raises(ValueError, match="defaults"):
        NativeSubagentPolicy(
            NativeSubagentLimits(2, 4, 2),
            NativeSubagentLimits(1, 4, 2),
        )
    with pytest.raises(ValueError, match="max_concurrent"):
        NativeSubagentLimits(MAX_NATIVE_SUBAGENTS_CONCURRENT + 1, 17, 1)
    with pytest.raises(ValueError, match="disabled"):
        NativeSubagentLimits(0, 0, 1)


def test_pins_require_lowercase_sha256_and_selected_skill_limit_is_bounded() -> None:
    skill = _skill()
    profile = _profile(skill)
    with pytest.raises(ValueError, match="sha256"):
        BirthPolicyRequest(ProfileVersionPin(profile.name, profile.version, "sha256:BAD"))

    selected = tuple(
        SkillVersionPin(f"skill-{index}", "1.0.0", _digest("d"))
        for index in range(33)
    )
    with pytest.raises(ValueError, match="limit of 32"):
        BirthPolicyRequest(profile.pin, selected)
