"""Bounded immutable values for governed Codex birth policies."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum

from .execution import SandboxPolicy

MAX_CONTENT_REFERENCE_LENGTH = 512
MAX_RUNTIME_TOOLS = 32
MAX_NATIVE_SUBAGENTS_CONCURRENT = 16
MAX_NATIVE_SUBAGENTS_TOTAL = 64
MAX_NATIVE_SUBAGENT_DEPTH = 4

_NAME = re.compile(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*\Z")
_SEMVER = re.compile(
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)"
    r"(?:-(?:[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+(?:[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?\Z"
)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_VERB = re.compile(
    r"[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)+\Z"
)
_PATH_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,95}\Z")
_MUTABLE_MODEL_SEGMENTS = frozenset(
    {
        "auto",
        "beta",
        "current",
        "default",
        "experimental",
        "latest",
        "preview",
        "recommended",
        "stable",
    }
)


def _has_control(value: str) -> bool:
    return any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in value)


def governed_name(label: str, value: object) -> str:
    """Return one canonical non-path identifier used by a governed catalogue."""

    if type(value) is not str:
        raise TypeError(f"{label} must be an exact string")
    if len(value) > 96 or _NAME.fullmatch(value) is None:
        raise ValueError(f"{label} must be a bounded canonical identifier")
    return value


def semantic_version(label: str, value: object) -> str:
    """Reject mutable labels and accept only an exact bounded SemVer."""

    if type(value) is not str:
        raise TypeError(f"{label} must be an exact string")
    if len(value) > 96 or _SEMVER.fullmatch(value) is None:
        raise ValueError(f"{label} must be an exact semantic version")
    prerelease = value.split("+", 1)[0].partition("-")[2]
    if any(
        part.isdigit() and len(part) > 1 and part.startswith("0")
        for part in prerelease.split(".")
    ):
        raise ValueError(f"{label} must be an exact semantic version")
    return value


def sha256_digest(label: str, value: object) -> str:
    if type(value) is not str:
        raise TypeError(f"{label} must be an exact string")
    if _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase sha256 digest")
    return value


def content_reference(value: object) -> str:
    """Validate a relative catalogue reference, never a host filesystem path."""

    if type(value) is not str:
        raise TypeError("content reference must be an exact string")
    if (
        not value
        or len(value) > MAX_CONTENT_REFERENCE_LENGTH
        or value != value.strip()
        or value.startswith("/")
        or value.endswith("/")
        or "\\" in value
        or _has_control(value)
    ):
        raise ValueError("content reference must be a bounded normalized relative path")
    components = value.split("/")
    if any(
        component in {"", ".", ".."} or _PATH_COMPONENT.fullmatch(component) is None
        for component in components
    ):
        raise ValueError("content reference must be a bounded normalized relative path")
    return value


def concrete_verbs(values: object, *, maximum: int) -> tuple[str, ...]:
    """Canonicalize exact domain verb requirements; wildcards are never accepted."""

    if type(values) is not tuple:
        raise TypeError("required verbs must be an immutable tuple")
    if len(values) > maximum:
        raise ValueError(f"required verbs exceed the limit of {maximum}")
    result: list[str] = []
    for value in values:
        if type(value) is not str:
            raise TypeError("required verb must be an exact string")
        if len(value) > 160 or _VERB.fullmatch(value) is None or "*" in value:
            raise ValueError("required verbs must be concrete canonical identifiers")
        result.append(value)
    if len(result) != len(set(result)):
        raise ValueError("required verbs must be unique")
    return tuple(sorted(result))


def runtime_tools(values: object, *, maximum: int = MAX_RUNTIME_TOOLS) -> tuple[str, ...]:
    """Canonicalize runtime tool identifiers without treating them as domain grants."""

    if type(values) is not tuple:
        raise TypeError("runtime tools must be an immutable tuple")
    if len(values) > maximum:
        raise ValueError(f"runtime tools exceed the limit of {maximum}")
    result = [governed_name("runtime tool", value) for value in values]
    if len(result) != len(set(result)):
        raise ValueError("runtime tools must be unique")
    return tuple(sorted(result))


def document_digest(document: object) -> str:
    encoded = json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class ReasoningEffort(str, Enum):
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"


@dataclass(frozen=True)
class DigestPinnedContent:
    """A logical catalogue path whose bytes must match one immutable digest."""

    reference: str
    digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "reference", content_reference(self.reference))
        object.__setattr__(self, "digest", sha256_digest("content digest", self.digest))


@dataclass(frozen=True)
class ExactModelPolicy:
    """One exact Codex model choice, with no fallback or prompt-controlled alias."""

    model_id: str
    reasoning_effort: ReasoningEffort

    def __post_init__(self) -> None:
        model_id = governed_name("model_id", self.model_id)
        segments = set(re.split(r"[._-]", model_id))
        if segments & _MUTABLE_MODEL_SEGMENTS:
            raise ValueError("model_id must not use a mutable model alias")
        if type(self.reasoning_effort) is not ReasoningEffort:
            raise TypeError("reasoning_effort must be an exact ReasoningEffort")
        object.__setattr__(self, "model_id", model_id)


@dataclass(frozen=True)
class RuntimeToolPolicy:
    """Default runtime tools and a static ceiling; neither grants domain authority."""

    defaults: tuple[str, ...] = ()
    ceiling: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        defaults = runtime_tools(self.defaults)
        ceiling = runtime_tools(self.ceiling)
        if not set(defaults) <= set(ceiling):
            raise ValueError("default runtime tools must be within the profile ceiling")
        object.__setattr__(self, "defaults", defaults)
        object.__setattr__(self, "ceiling", ceiling)


@dataclass(frozen=True, order=True)
class NativeSubagentLimits:
    """A bounded budget for Codex-native subagents inside one phase."""

    max_concurrent: int = 0
    max_total: int = 0
    max_depth: int = 0

    def __post_init__(self) -> None:
        values = (self.max_concurrent, self.max_total, self.max_depth)
        if any(type(value) is not int for value in values):
            raise TypeError("native subagent limits must be exact integers")
        if not 0 <= self.max_concurrent <= MAX_NATIVE_SUBAGENTS_CONCURRENT:
            raise ValueError("max_concurrent exceeds the native subagent limit")
        if not 0 <= self.max_total <= MAX_NATIVE_SUBAGENTS_TOTAL:
            raise ValueError("max_total exceeds the native subagent limit")
        if not 0 <= self.max_depth <= MAX_NATIVE_SUBAGENT_DEPTH:
            raise ValueError("max_depth exceeds the native subagent limit")
        if self.max_total == 0 and values != (0, 0, 0):
            raise ValueError("disabled native subagents require zero limits")
        if self.max_total > 0 and (
            self.max_concurrent < 1
            or self.max_depth < 1
            or self.max_concurrent > self.max_total
        ):
            raise ValueError("enabled native subagent limits are inconsistent")

    def within(self, ceiling: NativeSubagentLimits) -> bool:
        if type(ceiling) is not NativeSubagentLimits:
            raise TypeError("native subagent ceiling must be exact NativeSubagentLimits")
        return (
            self.max_concurrent <= ceiling.max_concurrent
            and self.max_total <= ceiling.max_total
            and self.max_depth <= ceiling.max_depth
        )


@dataclass(frozen=True)
class NativeSubagentPolicy:
    defaults: NativeSubagentLimits = NativeSubagentLimits()
    ceiling: NativeSubagentLimits = NativeSubagentLimits()

    def __post_init__(self) -> None:
        if type(self.defaults) is not NativeSubagentLimits:
            raise TypeError("native subagent defaults must be exact NativeSubagentLimits")
        if type(self.ceiling) is not NativeSubagentLimits:
            raise TypeError("native subagent ceiling must be exact NativeSubagentLimits")
        if not self.defaults.within(self.ceiling):
            raise ValueError("native subagent defaults must be within the profile ceiling")


def sandbox_within(value: SandboxPolicy, ceiling: SandboxPolicy) -> bool:
    if type(value) is not SandboxPolicy or type(ceiling) is not SandboxPolicy:
        raise TypeError("sandbox values must be exact SandboxPolicy values")
    rank = {SandboxPolicy.READ_ONLY: 0, SandboxPolicy.WORKSPACE_WRITE: 1}
    return rank[value] <= rank[ceiling]


__all__ = [
    "DigestPinnedContent",
    "ExactModelPolicy",
    "MAX_NATIVE_SUBAGENT_DEPTH",
    "MAX_NATIVE_SUBAGENTS_CONCURRENT",
    "MAX_NATIVE_SUBAGENTS_TOTAL",
    "MAX_RUNTIME_TOOLS",
    "NativeSubagentLimits",
    "NativeSubagentPolicy",
    "ReasoningEffort",
    "RuntimeToolPolicy",
    "concrete_verbs",
    "document_digest",
    "governed_name",
    "runtime_tools",
    "sandbox_within",
    "semantic_version",
    "sha256_digest",
]
