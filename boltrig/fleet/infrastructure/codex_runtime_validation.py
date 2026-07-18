"""Fail-closed validation at the Codex ``AgentRuntime`` boundary."""

from __future__ import annotations

import re

from boltrig.fleet.domain import (
    CanonicalJSON,
    OrganisationUserRef,
    PhaseAssignmentRef,
    PhaseMode,
    PhaseRef,
    ProfileRef,
    RuntimeThreadRef,
    RuntimeTurnRef,
    SandboxPolicy,
    SkillVersionRef,
)
from boltrig.fleet.ports.runtime import RuntimeThreadSpec, RuntimeTurnSpec, TurnSteerRequest

from . import codex_client_support as support
from .codex_runtime_admission import (
    AdmittedCodexCell,
    CodexRuntimeAdmissionError,
)

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


class CodexRuntimeBindingError(RuntimeError):
    """A lifecycle call did not match its exact active Boltrig binding."""


def validate_thread_spec(spec: object) -> RuntimeThreadSpec:
    if type(spec) is not RuntimeThreadSpec:
        raise TypeError("spec must be an exact RuntimeThreadSpec")
    validate_assignment(spec.assignment)
    if type(spec.profile) is not ProfileRef or type(spec.skills) is not tuple:
        raise TypeError("thread spec policy references must be exact")
    if any(type(skill) is not SkillVersionRef for skill in spec.skills):
        raise TypeError("thread spec skill references must be exact")
    if spec.mode is not PhaseMode.READ_ONLY or spec.sandbox is not SandboxPolicy.READ_ONLY:
        raise CodexRuntimeAdmissionError("first Codex runtime supports read-only phases only")
    if type(spec.metadata) is not CanonicalJSON:
        raise TypeError("thread spec metadata must be CanonicalJSON")
    support.require_absolute_cwd(spec.working_directory)
    return spec


def validate_admission(spec: RuntimeThreadSpec, leased: object) -> AdmittedCodexCell:
    if type(leased) is not AdmittedCodexCell or leased.admission.assignment != spec.assignment:
        raise CodexRuntimeAdmissionError("cell provider returned another assignment")
    admission = leased.admission
    policy = admission.compilation.policy
    if spec.working_directory != admission.layout.workspace.as_posix():
        raise CodexRuntimeAdmissionError("working directory is not the admitted workspace")
    if (spec.profile.name, spec.profile.version) != (policy.profile.name, policy.profile.version):
        raise CodexRuntimeAdmissionError("profile does not match the admitted birth policy")
    expected = tuple((pin.name, pin.version) for pin in policy.selected_skills)
    actual = tuple(sorted((skill.name, skill.version) for skill in spec.skills))
    if actual != expected:
        raise CodexRuntimeAdmissionError("skills do not match the admitted birth policy")
    return leased


def validate_turn_spec(spec: object) -> RuntimeTurnSpec:
    if type(spec) is not RuntimeTurnSpec:
        raise TypeError("turn spec and thread must be exact runtime values")
    validate_thread_ref(spec.thread)
    support.require_prompt(spec.prompt)
    client_identifier("client message id", spec.client_message_id)
    support.require_output_schema(spec.output_schema)
    return spec


def validate_steer_request(request: object) -> TurnSteerRequest:
    if type(request) is not TurnSteerRequest:
        raise TypeError("steer request and turn must be exact runtime values")
    validate_turn_ref(request.turn)
    support.require_prompt(request.prompt)
    client_identifier("client message id", request.client_message_id)
    return request


def client_identifier(label: str, value: object) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{label} must be a bounded canonical identifier")
    return value


def runtime_identifier(label: str, value: object) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise CodexRuntimeBindingError(f"Codex {label} is invalid")
    return value


def validate_assignment(value: object) -> PhaseAssignmentRef:
    if type(value) is not PhaseAssignmentRef or type(value.phase) is not PhaseRef:
        raise TypeError("assignment and phase must be exact runtime values")
    if type(value.phase.principal) is not OrganisationUserRef:
        raise TypeError("assignment principal must be an exact OrganisationUserRef")
    return value


def validate_thread_ref(value: object) -> RuntimeThreadRef:
    if type(value) is not RuntimeThreadRef:
        raise TypeError("thread must be an exact RuntimeThreadRef")
    validate_assignment(value.assignment)
    return value


def validate_turn_ref(value: object) -> RuntimeTurnRef:
    if type(value) is not RuntimeTurnRef:
        raise TypeError("turn must be an exact RuntimeTurnRef")
    validate_thread_ref(value.thread)
    return value


def copied_output_schema(value: CanonicalJSON | None) -> CanonicalJSON | None:
    """Copy a schema so a malformed mutable backing value cannot race the request."""

    checked = support.require_output_schema(value)
    return None if checked is None else CanonicalJSON.from_value(checked.to_value())


__all__ = [
    "CodexRuntimeBindingError",
    "copied_output_schema",
    "runtime_identifier",
    "validate_admission",
    "validate_steer_request",
    "validate_thread_spec",
    "validate_turn_ref",
    "validate_turn_spec",
]
