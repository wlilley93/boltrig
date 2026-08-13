from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from boltrig.fleet.domain.profile_policy import VersionedSkillManifest
from boltrig.fleet.domain.profile_policy_values import (
    DigestPinnedContent,
    NativeSubagentLimits,
)
from boltrig.fleet.domain.skill_attestation import (
    ExpectedSkill,
    ObservedSkill,
    SkillAttestationPlan,
    SkillDiscoveryReport,
    SkillScope,
    attest_skill_discovery,
)
from boltrig.fleet.infrastructure.codex_app_server import CodexAppServerClient
from boltrig.fleet.infrastructure.codex_cell_policy import CodexCellLayout
from boltrig.fleet.infrastructure.codex_cell_supervisor import (
    CodexCellMetadata,
    CodexCellSupervisor,
    InitializedCodexCell,
)
from boltrig.fleet.infrastructure.codex_runtime_admission import (
    AdmittedCodexCell,
    CodexPhaseAdmission,
    CodexRuntimeAdmissionError,
    CodexWorkspaceProjectionBinding,
    QUARANTINED_PREFLIGHT_BLOCKERS,
    QuarantinedCodexPreflightReceipt,
    SupervisedCodexPhaseCellProvider,
)
from boltrig.fleet.infrastructure.codex_runtime_surface_evidence import (
    QuarantinedCodexSurfaceEvidence,
    canonical_surface_digest,
)

from .codex_runtime_fakes import (
    INSTRUCTIONS,
    FakeCodexCell,
    admission,
    digest,
    fake_cell,
    preflight_receipt,
)


class _Source:
    def __init__(self, value: CodexPhaseAdmission) -> None:
        self.value = value
        self.calls = 0

    async def admit(self, _assignment: object) -> CodexPhaseAdmission:
        self.calls += 1
        return self.value


class _Supervisor:
    def __init__(self, cell: FakeCodexCell) -> None:
        self.cell = cell
        self.calls = 0

    async def start(
        self, _layout: CodexCellLayout, *, arguments: tuple[str, ...]
    ) -> InitializedCodexCell:
        self.calls += 1
        # Mirrors the real signature (H5): a double looser than the thing it
        # stands for would let an unpinned spawn pass here and fail in production.
        self.arguments = arguments
        return self.cell.initialized


class _Probe:
    def __init__(self, receipt: QuarantinedCodexPreflightReceipt) -> None:
        self.receipt = receipt
        self.calls = 0

    async def probe(
        self,
        _client: CodexAppServerClient,
        _plan: SkillAttestationPlan,
    ) -> QuarantinedCodexPreflightReceipt:
        self.calls += 1
        return self.receipt


def _drift_metadata(metadata: CodexCellMetadata, field: str) -> CodexCellMetadata:
    if field == "phase_id":
        return replace(metadata, phase_id="phase-other")
    if field == "cell_id":
        return replace(metadata, cell_id="cell-other")
    if field == "cli_version":
        return replace(metadata, cli_version="0.145.0")
    if field == "cli_target":
        return replace(metadata, cli_target="aarch64-unknown-linux-musl")
    if field == "binary_sha256":
        return replace(metadata, binary_sha256="0" * 64)
    if field == "workspace":
        return replace(metadata, workspace=Path("/srv/boltrig/cells/cell-1/other"))
    if field == "workspace_digest":
        return replace(metadata, workspace_digest=digest("workspace-other"))
    if field == "home":
        return replace(metadata, home=Path("/srv/boltrig/cells/cell-1/other-home"))
    if field == "codex_home":
        return replace(
            metadata,
            codex_home=Path("/srv/boltrig/cells/cell-1/other-codex-home"),
        )
    raise AssertionError(f"unhandled metadata field: {field}")


@pytest.mark.parametrize(
    "field",
    (
        "phase_id",
        "cell_id",
        "cli_version",
        "cli_target",
        "binary_sha256",
        "workspace",
        "workspace_digest",
        "home",
        "codex_home",
    ),
)
async def test_supervised_provider_rejects_every_bound_metadata_drift(
    field: str,
) -> None:
    value = admission()
    cell = fake_cell(value)
    cell.initialized.metadata = _drift_metadata(cell.initialized.metadata, field)
    source = _Source(value)
    supervisor = _Supervisor(cell)
    probe = _Probe(preflight_receipt(value))
    provider = SupervisedCodexPhaseCellProvider(
        source,
        cast(CodexCellSupervisor, supervisor),
        probe,
    )

    with pytest.raises(CodexRuntimeAdmissionError, match="initialized cell"):
        await provider.acquire(value.assignment)

    assert source.calls == supervisor.calls == 1
    assert probe.calls == 0
    assert cell.closed and cell.close_calls == 1


def test_admission_rejects_assignment_and_projection_scope_drift() -> None:
    value = admission()
    projection = value.layout.workspace_projection

    with pytest.raises(CodexRuntimeAdmissionError, match="cell phase"):
        replace(value, layout=replace(value.layout, phase_id="phase-other"))

    other_assignment = replace(value.assignment, assignment_id="assignment-other")
    with pytest.raises(CodexRuntimeAdmissionError, match="workspace scope"):
        replace(
            value,
            workspace_binding=CodexWorkspaceProjectionBinding(
                other_assignment,
                projection,
            ),
        )

    other_projection = replace(
        projection,
        source_path="/srv/boltrig/sources/workspace-other",
    )
    with pytest.raises(CodexRuntimeAdmissionError, match="workspace scope"):
        replace(
            value,
            workspace_binding=CodexWorkspaceProjectionBinding(
                value.assignment,
                other_projection,
            ),
        )

    with pytest.raises(CodexRuntimeAdmissionError, match="skill plan workspace"):
        replace(
            value,
            skill_plan=replace(
                value.skill_plan,
                workspace_path="/srv/boltrig/cells/cell-1/workspace-other",
            ),
        )


def _skill() -> VersionedSkillManifest:
    return VersionedSkillManifest(
        "evidence-review",
        "1.2.3",
        DigestPinnedContent(
            "skills/evidence-review/1.2.3/SKILL.md",
            digest("skill-manifest"),
        ),
        digest("skill-directory"),
    )


def test_admission_rejects_selected_skill_pin_and_version_drift() -> None:
    skill = _skill()
    value = admission(skill_manifests=(skill,))
    drifted_pin = replace(skill, required_domain_verbs=("matter.read",))
    drifted_version = replace(
        skill,
        version="1.2.4",
        artifact=replace(
            skill.artifact,
            reference="skills/evidence-review/1.2.4/SKILL.md",
        ),
    )

    for manifest in (drifted_pin, drifted_version):
        with pytest.raises(CodexRuntimeAdmissionError, match="skill pins"):
            replace(value, selected_skill_manifests=(manifest,))


def _drift_expected_skill(item: ExpectedSkill, field: str) -> ExpectedSkill:
    if field == "path":
        return replace(
            item,
            manifest_path=("/srv/boltrig/cells/cell-1/codex-home/skills/other/SKILL.md"),
        )
    if field == "directory_digest":
        return replace(item, directory_digest=digest("other-directory"))
    if field == "manifest_digest":
        return replace(item, manifest_digest=digest("other-manifest"))
    raise AssertionError(f"unhandled skill field: {field}")


@pytest.mark.parametrize("field", ("path", "directory_digest", "manifest_digest"))
def test_admission_rejects_skill_artifact_binding_drift(field: str) -> None:
    value = admission(skill_manifests=(_skill(),))
    observed = _drift_expected_skill(value.skill_plan.selected[0], field)

    with pytest.raises(CodexRuntimeAdmissionError, match="skill artifact binding"):
        replace(
            value,
            skill_plan=replace(value.skill_plan, selected=(observed,)),
        )


def _drift_receipt(
    receipt: QuarantinedCodexPreflightReceipt,
    field: str,
) -> QuarantinedCodexPreflightReceipt:
    if field == "protocol_version":
        return replace(receipt, protocol_version="0.145.0")
    if field == "protocol_bundle_digest":
        return replace(receipt, protocol_bundle_digest=digest("other-protocol-bundle"))
    if field == "missing_blocker":
        return replace(receipt, production_blockers=QUARANTINED_PREFLIGHT_BLOCKERS[:-1])
    if field == "extra_blocker":
        return replace(
            receipt,
            production_blockers=(*QUARANTINED_PREFLIGHT_BLOCKERS, "unknown_blocker"),
        )
    if field == "reordered_blockers":
        return replace(
            receipt,
            production_blockers=tuple(reversed(QUARANTINED_PREFLIGHT_BLOCKERS)),
        )
    raise AssertionError(f"unhandled receipt field: {field}")


@pytest.mark.parametrize(
    ("field", "message"),
    (
        ("protocol_version", "another protocol"),
        ("protocol_bundle_digest", "schema bundle"),
        ("missing_blocker", "production blocker"),
        ("extra_blocker", "production blocker"),
        ("reordered_blockers", "production blocker"),
    ),
)
def test_quarantined_receipt_rejects_protocol_or_blocker_drift(
    field: str,
    message: str,
) -> None:
    receipt = preflight_receipt(admission())

    with pytest.raises(CodexRuntimeAdmissionError, match=message):
        _drift_receipt(receipt, field)


def test_quarantined_receipt_keeps_the_complete_fixed_blocker_set() -> None:
    receipt = preflight_receipt(admission())

    assert receipt.production_blockers == QUARANTINED_PREFLIGHT_BLOCKERS
    assert receipt.production_blockers == (
        "effective_apps",
        "effective_config",
        "effective_external_agents",
        "effective_plugins",
        "effective_provider",
        "effective_tools",
        "full_generated_schema_contract",
    )
    assert not receipt.production_complete


@pytest.mark.parametrize("field", ("observed_mcp_server_count", "observed_hook_count"))
def test_quarantined_receipt_rejects_boolean_inventory_counts(field: str) -> None:
    receipt = preflight_receipt(admission())

    with pytest.raises(CodexRuntimeAdmissionError, match="external inventory"):
        replace(receipt, **{field: False})


@pytest.mark.parametrize(
    "limits",
    (
        NativeSubagentLimits(1, 1, 1),
        NativeSubagentLimits(1, 2, 1),
        NativeSubagentLimits(2, 2, 2),
    ),
)
@pytest.mark.invariant("SEC-159")
def test_quarantined_admission_requires_all_native_limits_to_be_zero(
    limits: NativeSubagentLimits,
) -> None:
    with pytest.raises(CodexRuntimeAdmissionError, match="native agents"):
        admission(native_limits=limits)

    assert admission().compilation.policy.native_subagents == NativeSubagentLimits()


def _admitted(
    value: CodexPhaseAdmission,
    receipt: QuarantinedCodexPreflightReceipt | None = None,
) -> AdmittedCodexCell:
    return AdmittedCodexCell(
        value,
        fake_cell(value).initialized,
        receipt or preflight_receipt(value),
    )


def test_evidence_digest_is_sensitive_to_each_admitted_evidence_layer() -> None:
    value = admission()
    baseline = _admitted(value)

    assignment_variant = _admitted(admission(replace(value.assignment, assignment_id="other")))

    cell_layout = replace(value.layout, cell_id="cell-other")
    cell_variant = _admitted(replace(value, layout=cell_layout))

    projection = replace(
        value.layout.workspace_projection,
        workspace_digest=digest("workspace-other"),
    )
    projection_variant_admission = replace(
        value,
        layout=replace(value.layout, workspace_projection=projection),
        workspace_binding=CodexWorkspaceProjectionBinding(value.assignment, projection),
    )
    projection_variant = _admitted(projection_variant_admission)

    plan_variant_admission = replace(
        value,
        skill_plan=replace(value.skill_plan, generation=value.skill_plan.generation + 1),
    )
    plan_variant = _admitted(plan_variant_admission)

    disabled_observation = ObservedSkill(
        "unselected",
        "/srv/boltrig/cells/cell-1/codex-home/skills/unselected/SKILL.md",
        SkillScope.USER,
        False,
    )
    report = SkillDiscoveryReport(
        value.skill_plan.workspace_path,
        (disabled_observation,),
    )
    receipt_variant = QuarantinedCodexPreflightReceipt(
        attest_skill_discovery(value.skill_plan, report)
    )
    preflight_variant = _admitted(value, receipt_variant)

    evidence = {
        baseline.evidence_digest(),
        assignment_variant.evidence_digest(),
        cell_variant.evidence_digest(),
        projection_variant.evidence_digest(),
        plan_variant.evidence_digest(),
        preflight_variant.evidence_digest(),
    }
    assert len(evidence) == 6
    assert baseline.evidence_digest() == baseline.evidence_digest()


def test_evidence_digest_and_admission_repr_do_not_expose_birth_instructions() -> None:
    value = admission()
    admitted = _admitted(value)
    evidence = admitted.evidence_digest()

    assert re.fullmatch(r"sha256:[0-9a-f]{64}", evidence)
    assert INSTRUCTIONS not in evidence
    assert INSTRUCTIONS not in repr(value)
    assert INSTRUCTIONS not in repr(admitted)


@pytest.mark.invariant("SEC-159")
def test_surface_receipt_cannot_claim_a_tool_ceiling_the_admission_did_not_grant() -> None:
    value = admission()
    cell = fake_cell(value)
    base = preflight_receipt(value)
    empty = canonical_surface_digest({})
    surface = QuarantinedCodexSurfaceEvidence(
        effective_config_digest=empty,
        composed_config_digest=empty,
        apps_inventory_digest=empty,
        plugins_inventory_digest=empty,
        external_agents_inventory_digest=empty,
        effective_tools_digest=canonical_surface_digest(("device.file.list",)),
    )
    receipt = replace(base, surface_evidence=surface)

    with pytest.raises(CodexRuntimeAdmissionError, match="tool ceiling"):
        AdmittedCodexCell(value, cell.initialized, receipt)
