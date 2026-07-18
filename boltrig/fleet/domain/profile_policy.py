"""Static profiles, versioned skill manifests, and compiled birth policy values."""

from __future__ import annotations

from dataclasses import dataclass, field

from boltrig.models import ProfileVersionPin, SkillVersionPin

from .execution import SandboxPolicy
from .profile_policy_values import (
    DigestPinnedContent,
    ExactModelPolicy,
    NativeSubagentLimits,
    NativeSubagentPolicy,
    RuntimeToolPolicy,
    concrete_verbs,
    document_digest,
    governed_name,
    runtime_tools,
    sandbox_within,
    semantic_version,
    sha256_digest,
)

MAX_PROFILE_SKILLS = 64
MAX_SELECTED_SKILLS = 32
MAX_SKILL_REQUIRED_VERBS = 128
MAX_COMPILED_REQUIRED_VERBS = 256
BIRTH_POLICY_COMPILER_VERSION = "1.0.0"


def _pin_document(pin: ProfileVersionPin | SkillVersionPin) -> dict[str, str]:
    return {"digest": pin.digest, "name": pin.name, "version": pin.version}


def _content_document(content: DigestPinnedContent) -> dict[str, str]:
    return {"digest": content.digest, "reference": content.reference}


def _limits_document(limits: NativeSubagentLimits) -> dict[str, int]:
    return {
        "max_concurrent": limits.max_concurrent,
        "max_depth": limits.max_depth,
        "max_total": limits.max_total,
    }


def _strict_profile_pin(value: object) -> ProfileVersionPin:
    if type(value) is not ProfileVersionPin:
        raise TypeError("profile pin must be an exact ProfileVersionPin")
    governed_name("profile pin name", value.name)
    semantic_version("profile pin version", value.version)
    sha256_digest("profile pin digest", value.digest)
    return value


def _strict_skill_pin(value: object) -> SkillVersionPin:
    if type(value) is not SkillVersionPin:
        raise TypeError("skill pin must be an exact SkillVersionPin")
    governed_name("skill pin name", value.name)
    semantic_version("skill pin version", value.version)
    sha256_digest("skill pin digest", value.digest)
    return value


def _skill_pins(values: object, *, maximum: int, label: str) -> tuple[SkillVersionPin, ...]:
    if type(values) is not tuple:
        raise TypeError(f"{label} must be an immutable tuple")
    if len(values) > maximum:
        raise ValueError(f"{label} exceeds the limit of {maximum}")
    pins = [_strict_skill_pin(value) for value in values]
    names = [pin.name for pin in pins]
    if len(names) != len(set(names)):
        raise ValueError(f"{label} must be unique by skill name")
    return tuple(sorted(pins, key=lambda pin: (pin.name, pin.version, pin.digest)))


@dataclass(frozen=True)
class VersionedSkillManifest:
    """Digest-pinned skill artifact requirements; selecting this grants nothing."""

    name: str
    version: str
    artifact: DigestPinnedContent
    artifact_directory_digest: str
    required_domain_verbs: tuple[str, ...] = ()
    required_runtime_tools: tuple[str, ...] = ()
    minimum_sandbox: SandboxPolicy = SandboxPolicy.READ_ONLY

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", governed_name("skill name", self.name))
        object.__setattr__(self, "version", semantic_version("skill version", self.version))
        if type(self.artifact) is not DigestPinnedContent:
            raise TypeError("skill artifact must be exact DigestPinnedContent")
        if not self.artifact.reference.endswith("/SKILL.md"):
            raise ValueError("skill artifact reference must end in SKILL.md")
        expected_prefix = f"skills/{self.name}/{self.version}/"
        if not self.artifact.reference.startswith(expected_prefix):
            raise ValueError("skill artifact reference must match its name and version")
        sha256_digest("skill artifact directory digest", self.artifact_directory_digest)
        object.__setattr__(
            self,
            "required_domain_verbs",
            concrete_verbs(
                self.required_domain_verbs,
                maximum=MAX_SKILL_REQUIRED_VERBS,
            ),
        )
        object.__setattr__(
            self,
            "required_runtime_tools",
            runtime_tools(self.required_runtime_tools),
        )
        if type(self.minimum_sandbox) is not SandboxPolicy:
            raise TypeError("minimum_sandbox must be an exact SandboxPolicy")

    def definition_digest(self) -> str:
        return document_digest(
            {
                "artifact": {
                    "directory_digest": self.artifact_directory_digest,
                    "manifest": _content_document(self.artifact),
                },
                "minimum_sandbox": self.minimum_sandbox.value,
                "name": self.name,
                "required_domain_verbs": self.required_domain_verbs,
                "required_runtime_tools": self.required_runtime_tools,
                "version": self.version,
            }
        )

    @property
    def pin(self) -> SkillVersionPin:
        return SkillVersionPin(self.name, self.version, self.definition_digest())


@dataclass(frozen=True)
class StaticRoleProfile:
    """Reusable immutable birth configuration selected by a governed phase."""

    name: str
    version: str
    instructions: DigestPinnedContent
    model: ExactModelPolicy
    tools: RuntimeToolPolicy
    default_sandbox: SandboxPolicy
    sandbox_ceiling: SandboxPolicy
    permitted_skills: tuple[SkillVersionPin, ...] = ()
    native_subagents: NativeSubagentPolicy = field(default_factory=NativeSubagentPolicy)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", governed_name("profile name", self.name))
        object.__setattr__(self, "version", semantic_version("profile version", self.version))
        if type(self.instructions) is not DigestPinnedContent:
            raise TypeError("profile instructions must be exact DigestPinnedContent")
        if not self.instructions.reference.endswith(".md"):
            raise ValueError("profile instructions must reference a Markdown artifact")
        expected_prefix = f"profiles/{self.name}/{self.version}/"
        if not self.instructions.reference.startswith(expected_prefix):
            raise ValueError("profile instructions must match its name and version")
        if type(self.model) is not ExactModelPolicy:
            raise TypeError("profile model must be exact ExactModelPolicy")
        if type(self.tools) is not RuntimeToolPolicy:
            raise TypeError("profile tools must be exact RuntimeToolPolicy")
        if not sandbox_within(self.default_sandbox, self.sandbox_ceiling):
            raise ValueError("default sandbox must be within the profile ceiling")
        object.__setattr__(
            self,
            "permitted_skills",
            _skill_pins(
                self.permitted_skills,
                maximum=MAX_PROFILE_SKILLS,
                label="permitted skill catalogue",
            ),
        )
        if type(self.native_subagents) is not NativeSubagentPolicy:
            raise TypeError("native_subagents must be exact NativeSubagentPolicy")

    def definition_digest(self) -> str:
        return document_digest(
            {
                "default_sandbox": self.default_sandbox.value,
                "instructions": _content_document(self.instructions),
                "model": {
                    "id": self.model.model_id,
                    "reasoning_effort": self.model.reasoning_effort.value,
                },
                "name": self.name,
                "native_subagents": {
                    "ceiling": _limits_document(self.native_subagents.ceiling),
                    "defaults": _limits_document(self.native_subagents.defaults),
                },
                "permitted_skills": [_pin_document(pin) for pin in self.permitted_skills],
                "sandbox_ceiling": self.sandbox_ceiling.value,
                "tools": {
                    "ceiling": self.tools.ceiling,
                    "defaults": self.tools.defaults,
                },
                "version": self.version,
            }
        )

    @property
    def pin(self) -> ProfileVersionPin:
        return ProfileVersionPin(self.name, self.version, self.definition_digest())


@dataclass(frozen=True)
class BirthPolicyRequest:
    """A policy-only selection request; prompts and grants are deliberately absent."""

    profile: ProfileVersionPin
    selected_skills: tuple[SkillVersionPin, ...] = ()
    requested_tools: tuple[str, ...] | None = None
    requested_sandbox: SandboxPolicy | None = None
    requested_native_subagents: NativeSubagentLimits | None = None

    def __post_init__(self) -> None:
        _strict_profile_pin(self.profile)
        object.__setattr__(
            self,
            "selected_skills",
            _skill_pins(
                self.selected_skills,
                maximum=MAX_SELECTED_SKILLS,
                label="selected skills",
            ),
        )
        if self.requested_tools is not None:
            object.__setattr__(self, "requested_tools", runtime_tools(self.requested_tools))
        if self.requested_sandbox is not None and type(
            self.requested_sandbox
        ) is not SandboxPolicy:
            raise TypeError("requested_sandbox must be an exact SandboxPolicy")
        if self.requested_native_subagents is not None and type(
            self.requested_native_subagents
        ) is not NativeSubagentLimits:
            raise TypeError(
                "requested_native_subagents must be exact NativeSubagentLimits"
            )

    def digest(self) -> str:
        return document_digest(
            {
                "native_subagents": (
                    None
                    if self.requested_native_subagents is None
                    else _limits_document(self.requested_native_subagents)
                ),
                "profile": _pin_document(self.profile),
                "sandbox": (
                    None
                    if self.requested_sandbox is None
                    else self.requested_sandbox.value
                ),
                "selected_skills": [_pin_document(pin) for pin in self.selected_skills],
                "tools": self.requested_tools,
            }
        )


@dataclass(frozen=True)
class CompiledBirthPolicy:
    """Exact bounded runtime configuration plus skill requirements, never grants."""

    profile: ProfileVersionPin
    instructions: DigestPinnedContent
    model: ExactModelPolicy
    enabled_tools: tuple[str, ...]
    tool_ceiling: tuple[str, ...]
    sandbox: SandboxPolicy
    sandbox_ceiling: SandboxPolicy
    native_subagents: NativeSubagentLimits
    native_subagent_ceiling: NativeSubagentLimits
    selected_skills: tuple[SkillVersionPin, ...]
    required_domain_verbs: tuple[str, ...]

    def __post_init__(self) -> None:
        _strict_profile_pin(self.profile)
        if type(self.instructions) is not DigestPinnedContent:
            raise TypeError("compiled instructions must be exact DigestPinnedContent")
        if type(self.model) is not ExactModelPolicy:
            raise TypeError("compiled model must be exact ExactModelPolicy")
        enabled = runtime_tools(self.enabled_tools)
        ceiling = runtime_tools(self.tool_ceiling)
        if not set(enabled) <= set(ceiling):
            raise ValueError("compiled tools exceed the profile ceiling")
        object.__setattr__(self, "enabled_tools", enabled)
        object.__setattr__(self, "tool_ceiling", ceiling)
        if not sandbox_within(self.sandbox, self.sandbox_ceiling):
            raise ValueError("compiled sandbox exceeds the profile ceiling")
        if type(self.native_subagents) is not NativeSubagentLimits or type(
            self.native_subagent_ceiling
        ) is not NativeSubagentLimits:
            raise TypeError("compiled native subagent values must be exact limits")
        if not self.native_subagents.within(self.native_subagent_ceiling):
            raise ValueError("compiled native subagents exceed the profile ceiling")
        object.__setattr__(
            self,
            "selected_skills",
            _skill_pins(
                self.selected_skills,
                maximum=MAX_SELECTED_SKILLS,
                label="compiled selected skills",
            ),
        )
        object.__setattr__(
            self,
            "required_domain_verbs",
            concrete_verbs(
                self.required_domain_verbs,
                maximum=MAX_COMPILED_REQUIRED_VERBS,
            ),
        )

    def digest(self) -> str:
        return document_digest(
            {
                "enabled_tools": self.enabled_tools,
                "instructions": _content_document(self.instructions),
                "model": {
                    "id": self.model.model_id,
                    "reasoning_effort": self.model.reasoning_effort.value,
                },
                "native_subagent_ceiling": _limits_document(
                    self.native_subagent_ceiling
                ),
                "native_subagents": _limits_document(self.native_subagents),
                "profile": _pin_document(self.profile),
                "required_domain_verbs": self.required_domain_verbs,
                "sandbox": self.sandbox.value,
                "sandbox_ceiling": self.sandbox_ceiling.value,
                "selected_skills": [
                    _pin_document(pin) for pin in self.selected_skills
                ],
                "tool_ceiling": self.tool_ceiling,
            }
        )


@dataclass(frozen=True)
class BirthPolicyEvidence:
    """Digest-only evidence tying catalogue inputs to one compiled policy."""

    request_digest: str
    profile_digest: str
    selected_catalog_digest: str
    compiled_policy_digest: str
    compiler_version: str = field(default=BIRTH_POLICY_COMPILER_VERSION, init=False)

    def __post_init__(self) -> None:
        sha256_digest("request digest", self.request_digest)
        sha256_digest("profile digest", self.profile_digest)
        sha256_digest("selected catalog digest", self.selected_catalog_digest)
        sha256_digest("compiled policy digest", self.compiled_policy_digest)


@dataclass(frozen=True)
class BirthPolicyCompilation:
    policy: CompiledBirthPolicy
    evidence: BirthPolicyEvidence

    def __post_init__(self) -> None:
        if type(self.policy) is not CompiledBirthPolicy:
            raise TypeError("policy must be exact CompiledBirthPolicy")
        if type(self.evidence) is not BirthPolicyEvidence:
            raise TypeError("evidence must be exact BirthPolicyEvidence")
        if self.policy.digest() != self.evidence.compiled_policy_digest:
            raise ValueError("compiled policy and audit evidence digests disagree")
        if self.policy.profile.digest != self.evidence.profile_digest:
            raise ValueError("profile pin and audit evidence digests disagree")
        expected_catalog = document_digest(
            {"skills": [_pin_document(pin) for pin in self.policy.selected_skills]}
        )
        if expected_catalog != self.evidence.selected_catalog_digest:
            raise ValueError("selected skill pins and audit evidence digests disagree")


def selected_catalog_digest(manifests: tuple[VersionedSkillManifest, ...]) -> str:
    pins = sorted((manifest.pin for manifest in manifests), key=lambda pin: pin.name)
    return document_digest({"skills": [_pin_document(pin) for pin in pins]})


__all__ = [
    "BIRTH_POLICY_COMPILER_VERSION",
    "BirthPolicyCompilation",
    "BirthPolicyEvidence",
    "BirthPolicyRequest",
    "CompiledBirthPolicy",
    "MAX_COMPILED_REQUIRED_VERBS",
    "MAX_PROFILE_SKILLS",
    "MAX_SELECTED_SKILLS",
    "MAX_SKILL_REQUIRED_VERBS",
    "StaticRoleProfile",
    "VersionedSkillManifest",
    "selected_catalog_digest",
]
