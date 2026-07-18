"""Trusted admission seam for one quarantined Codex phase cell."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from boltrig.fleet.domain import PhaseAssignmentRef, SandboxPolicy
from boltrig.fleet.domain.profile_policy import (
    BirthPolicyCompilation,
    VersionedSkillManifest,
)
from boltrig.fleet.domain.skill_attestation import (
    SkillAttestation,
    SkillAttestationPlan,
    SkillScope,
)

from .codex_app_server import CodexAppServerClient
from .codex_cell_policy import (
    CODEX_CLI_SHA256,
    CODEX_CLI_TARGET,
    CODEX_CLI_VERSION,
    CodexCellLayout,
)
from .codex_cell_supervisor import CodexCellSupervisor, InitializedCodexCell
from .skill_artifacts import SanitizedWorkspaceProjection

MAX_BIRTH_INSTRUCTIONS_BYTES = 128 * 1024
CODEX_PROTOCOL_BUNDLE_DIGEST = (
    "sha256:0194f4370fd6ec268f81270217b56b2d1133ecc2c2a1560f3870dd6ec16e9810"
)
QUARANTINED_PREFLIGHT_BLOCKERS = (
    "effective_apps",
    "effective_config",
    "effective_external_agents",
    "effective_plugins",
    "effective_provider",
    "effective_tools",
    "full_generated_schema_contract",
)


class CodexRuntimeAdmissionError(PermissionError):
    """A phase was not admitted to the exact quarantined read-only cell."""


@dataclass(frozen=True)
class CodexWorkspaceProjectionBinding:
    """Bind one exact assignment to its sanitized source and projected snapshot."""

    assignment: PhaseAssignmentRef
    projection: SanitizedWorkspaceProjection

    def __post_init__(self) -> None:
        if type(self.assignment) is not PhaseAssignmentRef:
            raise TypeError("assignment must be an exact PhaseAssignmentRef")
        if type(self.projection) is not SanitizedWorkspaceProjection:
            raise TypeError("projection must be an exact SanitizedWorkspaceProjection")

    def digest(self) -> str:
        phase = self.assignment.phase
        projection = self.projection
        return _document_digest(
            {
                "assignment_id": self.assignment.assignment_id,
                "file_count": projection.file_count,
                "phase_id": phase.phase_id,
                "principal_user_id": phase.principal.user_id,
                "projection_digest": projection.workspace_digest,
                "projection_path": projection.workspace_path,
                "projection_source": projection.source_path,
                "root_run_id": phase.root_run_id,
                "tenant_id": phase.principal.tenant_id,
                "total_bytes": projection.total_bytes,
                "workspace_id": phase.workspace_id,
            }
        )


@dataclass(frozen=True)
class QuarantinedCodexPreflightReceipt:
    """Incomplete evidence from the probes safe to run before ``thread/start``."""

    skill_attestation: SkillAttestation
    observed_mcp_server_count: int = 0
    observed_hook_count: int = 0
    protocol_version: str = CODEX_CLI_VERSION
    protocol_bundle_digest: str = CODEX_PROTOCOL_BUNDLE_DIGEST
    production_blockers: tuple[str, ...] = QUARANTINED_PREFLIGHT_BLOCKERS

    def __post_init__(self) -> None:
        if type(self.skill_attestation) is not SkillAttestation:
            raise TypeError("skill_attestation must be an exact SkillAttestation")
        if (
            type(self.observed_mcp_server_count) is not int
            or type(self.observed_hook_count) is not int
            or self.observed_mcp_server_count != 0
            or self.observed_hook_count != 0
        ):
            raise CodexRuntimeAdmissionError("quarantined external inventory must be empty")
        if self.protocol_version != CODEX_CLI_VERSION:
            raise CodexRuntimeAdmissionError("quarantined receipt uses another protocol")
        if self.protocol_bundle_digest != CODEX_PROTOCOL_BUNDLE_DIGEST:
            raise CodexRuntimeAdmissionError("quarantined receipt uses another schema bundle")
        if self.production_blockers != QUARANTINED_PREFLIGHT_BLOCKERS:
            raise CodexRuntimeAdmissionError("quarantined receipt omitted a production blocker")

    @property
    def production_complete(self) -> bool:
        return False

    def digest(self) -> str:
        return _document_digest(
            {
                "observed_hook_count": self.observed_hook_count,
                "observed_mcp_server_count": self.observed_mcp_server_count,
                "production_blockers": self.production_blockers,
                "production_complete": False,
                "protocol_bundle_digest": self.protocol_bundle_digest,
                "protocol_version": self.protocol_version,
                "skill_attestation": self.skill_attestation.digest,
            }
        )


@dataclass(frozen=True, repr=False)
class CodexPhaseAdmission:
    """Pre-provisioned cell and immutable birth policy for one assignment."""

    assignment: PhaseAssignmentRef
    layout: CodexCellLayout
    workspace_binding: CodexWorkspaceProjectionBinding
    compilation: BirthPolicyCompilation
    selected_skill_manifests: tuple[VersionedSkillManifest, ...]
    skill_plan: SkillAttestationPlan
    developer_instructions: str
    provisioned_policy_digest: str

    def __post_init__(self) -> None:
        _validate_admission_types(self)
        _validate_instruction_text(self.developer_instructions)
        policy = self.compilation.policy
        if self.layout.phase_id != self.assignment.phase.phase_id:
            raise CodexRuntimeAdmissionError("cell phase does not match the assignment")
        if (
            self.workspace_binding.assignment != self.assignment
            or self.workspace_binding.projection != self.layout.workspace_projection
        ):
            raise CodexRuntimeAdmissionError("workspace scope does not match the assignment")
        if policy.sandbox is not SandboxPolicy.READ_ONLY:
            raise CodexRuntimeAdmissionError("Codex runtime admission is read-only")
        if policy.enabled_tools:
            raise CodexRuntimeAdmissionError("quarantined runtime cannot attest effective tools")
        limits = policy.native_subagents
        if (limits.max_total, limits.max_concurrent, limits.max_depth) != (0, 0, 0):
            raise CodexRuntimeAdmissionError("native agents lack enforceable runtime controls")
        _validate_skill_bindings(self)
        if self.provisioned_policy_digest != policy.digest():
            raise CodexRuntimeAdmissionError("provisioned policy digest does not match")
        if _text_digest(self.developer_instructions) != policy.instructions.digest:
            raise CodexRuntimeAdmissionError("birth instructions do not match their pin")


@dataclass(frozen=True, repr=False)
class AdmittedCodexCell:
    """Initialized single-owner cell tied to exact admission and probe evidence."""

    admission: CodexPhaseAdmission
    cell: InitializedCodexCell
    quarantined_preflight: QuarantinedCodexPreflightReceipt

    def __post_init__(self) -> None:
        if type(self.admission) is not CodexPhaseAdmission:
            raise TypeError("admission must be an exact CodexPhaseAdmission")
        if type(self.cell) is not InitializedCodexCell:
            raise TypeError("cell must be an exact InitializedCodexCell")
        if type(self.quarantined_preflight) is not QuarantinedCodexPreflightReceipt:
            raise TypeError("preflight must be an exact QuarantinedCodexPreflightReceipt")
        _validate_initialized_cell(self.admission, self.cell)
        plan = self.admission.skill_plan
        proof = self.quarantined_preflight.skill_attestation
        if (
            proof.plan_digest != plan.digest()
            or proof.generation != plan.generation
            or proof.workspace_path != plan.workspace_path
            or proof.selected_names != tuple(sorted(item.name for item in plan.selected))
        ):
            raise CodexRuntimeAdmissionError("skill attestation does not match its admission")

    def evidence_digest(self) -> str:
        metadata = self.cell.metadata
        return _document_digest(
            {
                "assignment_id": self.admission.assignment.assignment_id,
                "binary_sha256": metadata.binary_sha256,
                "cell_id": metadata.cell_id,
                "cli_target": metadata.cli_target,
                "cli_version": metadata.cli_version,
                "codex_home": metadata.codex_home.as_posix(),
                "home": metadata.home.as_posix(),
                "policy": self.admission.compilation.policy.digest(),
                "preflight": self.quarantined_preflight.digest(),
                "protocol_bundle": CODEX_PROTOCOL_BUNDLE_DIGEST,
                "skill_plan": self.admission.skill_plan.digest(),
                "workspace_binding": self.admission.workspace_binding.digest(),
            }
        )


class CodexPhaseAdmissionSource(Protocol):
    async def admit(self, assignment: PhaseAssignmentRef) -> CodexPhaseAdmission: ...


class CodexPhaseCellProvider(Protocol):
    async def acquire(self, assignment: PhaseAssignmentRef) -> AdmittedCodexCell: ...


class CodexPreflightProbe(Protocol):
    """Run only the explicitly incomplete quarantined probes."""

    async def probe(
        self,
        client: CodexAppServerClient,
        plan: SkillAttestationPlan,
    ) -> QuarantinedCodexPreflightReceipt: ...


class SupervisedCodexPhaseCellProvider:
    """Validate admission and cell identity before any incomplete probe runs."""

    def __init__(
        self,
        source: CodexPhaseAdmissionSource,
        supervisor: CodexCellSupervisor,
        probe: CodexPreflightProbe,
    ) -> None:
        self._source = source
        self._supervisor = supervisor
        self._probe = probe

    async def acquire(self, assignment: PhaseAssignmentRef) -> AdmittedCodexCell:
        if type(assignment) is not PhaseAssignmentRef:
            raise TypeError("assignment must be an exact PhaseAssignmentRef")
        admission = await self._source.admit(assignment)
        if type(admission) is not CodexPhaseAdmission or admission.assignment != assignment:
            raise CodexRuntimeAdmissionError("admission source returned another assignment")
        cell = await self._supervisor.start(admission.layout)
        try:
            _validate_initialized_cell(admission, cell)
            preflight = await self._probe.probe(cell.client, admission.skill_plan)
            return AdmittedCodexCell(admission, cell, preflight)
        except BaseException:
            await _cleanup_ignoring_failure(cell.aclose)
            raise


def _validate_admission_types(value: CodexPhaseAdmission) -> None:
    if type(value.assignment) is not PhaseAssignmentRef:
        raise TypeError("assignment must be an exact PhaseAssignmentRef")
    if type(value.layout) is not CodexCellLayout:
        raise TypeError("layout must be an exact CodexCellLayout")
    if type(value.workspace_binding) is not CodexWorkspaceProjectionBinding:
        raise TypeError("workspace_binding must be exact")
    if type(value.compilation) is not BirthPolicyCompilation:
        raise TypeError("compilation must be an exact BirthPolicyCompilation")
    if type(value.selected_skill_manifests) is not tuple or any(
        type(item) is not VersionedSkillManifest for item in value.selected_skill_manifests
    ):
        raise TypeError("selected skill manifests must be exact immutable values")
    if type(value.skill_plan) is not SkillAttestationPlan:
        raise TypeError("skill_plan must be an exact SkillAttestationPlan")


def _validate_skill_bindings(value: CodexPhaseAdmission) -> None:
    manifests = value.selected_skill_manifests
    names = tuple(item.name for item in manifests)
    if names != tuple(sorted(set(names))):
        raise CodexRuntimeAdmissionError("selected skill manifests must be sorted and unique")
    if tuple(item.pin for item in manifests) != value.compilation.policy.selected_skills:
        raise CodexRuntimeAdmissionError("skill pins do not match their admitted artifacts")
    expected = {item.name: item for item in value.skill_plan.selected}
    if set(expected) != set(names):
        raise CodexRuntimeAdmissionError("skill plan does not match selected manifests")
    for manifest in manifests:
        observed = expected[manifest.name]
        path = value.layout.codex_home / "skills" / manifest.name / "SKILL.md"
        if (
            observed.scope is not SkillScope.USER
            or observed.manifest_path != path.as_posix()
            or observed.directory_digest != manifest.artifact_directory_digest
            or observed.manifest_digest != manifest.artifact.digest
        ):
            raise CodexRuntimeAdmissionError("skill artifact binding does not match its pin")
    if value.skill_plan.workspace_path != value.layout.workspace.as_posix():
        raise CodexRuntimeAdmissionError("skill plan workspace does not match the cell")


def _validate_initialized_cell(
    admission: CodexPhaseAdmission,
    cell: InitializedCodexCell,
) -> None:
    if type(cell) is not InitializedCodexCell:
        raise TypeError("cell must be an exact InitializedCodexCell")
    metadata = cell.metadata
    layout = admission.layout
    if (
        metadata.phase_id != admission.assignment.phase.phase_id
        or metadata.cell_id != layout.cell_id
        or metadata.cli_version != CODEX_CLI_VERSION
        or metadata.cli_target != CODEX_CLI_TARGET
        or metadata.binary_sha256 != CODEX_CLI_SHA256
        or metadata.workspace != layout.workspace
        or metadata.workspace_digest != layout.workspace_digest
        or metadata.home != layout.home
        or metadata.codex_home != layout.codex_home
    ):
        raise CodexRuntimeAdmissionError("initialized cell does not match its admission")


def _validate_instruction_text(value: object) -> str:
    if type(value) is not str or not value or value != value.strip() or "\x00" in value:
        raise CodexRuntimeAdmissionError("birth instructions must be bounded text")
    try:
        encoded = value.encode("utf-8")
    except UnicodeError:
        raise CodexRuntimeAdmissionError("birth instructions must be bounded text") from None
    if len(encoded) > MAX_BIRTH_INSTRUCTIONS_BYTES:
        raise CodexRuntimeAdmissionError("birth instructions must be bounded text")
    return value


def _text_digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _document_digest(value: dict[str, object]) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


async def _cleanup_ignoring_failure(callback: Callable[[], Awaitable[None]]) -> None:
    task: asyncio.Future[None] = asyncio.ensure_future(callback())
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.gather(task, return_exceptions=True)
    except BaseException:
        pass


__all__ = [
    "AdmittedCodexCell",
    "CODEX_PROTOCOL_BUNDLE_DIGEST",
    "CodexPhaseAdmission",
    "CodexPhaseAdmissionSource",
    "CodexPhaseCellProvider",
    "CodexPreflightProbe",
    "CodexRuntimeAdmissionError",
    "CodexWorkspaceProjectionBinding",
    "QUARANTINED_PREFLIGHT_BLOCKERS",
    "QuarantinedCodexPreflightReceipt",
    "SupervisedCodexPhaseCellProvider",
]
