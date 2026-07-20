"""A concrete read-only ``CodexPhaseAdmissionSource`` that provisions a cell.

The supervisor consumes a pre-provisioned, sanitized, read-only cell but never
creates one (codex_cell_policy: "an admission seam, not a builder"). This is the
seam that actually lays that cell down for one phase: it creates the fail-closed
directory layout (workspace ``0500``, HOME/CODEX_HOME ``0700``, owner-checked,
symlink-free), captures the workspace digest, compiles the fixed read-only birth
policy, and assembles a ``CodexPhaseAdmission`` that passes ``validate_cell_layout``
and ``CodexPhaseAdmission`` validation.

Scope: MVP read-only. The workspace is EMPTY (no source projection, no skills),
the profile is tool-free with native subagents disabled. Workspace/skill
projection and the write phase are later, court-gated work (PR8). Filesystem work
is blocking, so ``admit`` runs it in a worker thread.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from boltrig.fleet.application.birth_policies import compile_birth_policy
from boltrig.fleet.domain import PhaseAssignmentRef
from boltrig.fleet.domain.profile_policy import BirthPolicyRequest
from boltrig.fleet.domain.profile_policy_values import NativeSubagentLimits
from boltrig.fleet.domain.skill_attestation import SkillAttestationPlan

from .bounded_filesystem import capture_directory
from .cell_slots import CellSlot
from .codex_cell_policy import (
    CODEX_WORKSPACE_LIMITS,
    EMPTY_WORKSPACE_DIGEST,
    EMPTY_WORKSPACE_FILE_COUNT,
    EMPTY_WORKSPACE_TOTAL_BYTES,
    CodexCellLayout,
    normalized_absolute_path,
    validate_cell_layout,
)
from .codex_read_only_phase import (
    READ_ONLY_INSTRUCTIONS,
    read_only_cell_id,
    read_only_cell_root,
    read_only_static_profile,
)
from .codex_runtime_admission import (
    CodexPhaseAdmission,
    CodexWorkspaceProjectionBinding,
)
from .skill_artifacts import SanitizedWorkspaceProjection

_CELL_DIR_MODE = 0o700
_WORKSPACE_MODE = 0o500


class ProvisioningCodexPhaseAdmissionSource:
    """Provision + assemble a read-only Codex cell admission for one assignment."""

    def __init__(self, *, stack_root: Path | str, model_id: str) -> None:
        self._stack_root = normalized_absolute_path("codex stack root", Path(stack_root))
        if type(model_id) is not str or not model_id.strip():
            raise ValueError("codex model id must be a non-empty string")
        self._model_id = model_id

    async def admit(
        self, assignment: PhaseAssignmentRef, slot: CellSlot | None = None
    ) -> CodexPhaseAdmission:
        if type(assignment) is not PhaseAssignmentRef:
            raise TypeError("assignment must be an exact PhaseAssignmentRef")
        return await asyncio.to_thread(self._provision, assignment, slot)

    def _provision(
        self, assignment: PhaseAssignmentRef, slot: CellSlot | None = None
    ) -> CodexPhaseAdmission:
        if slot is not None:
            return self._provision_per_cell(assignment, slot)
        cell_id = read_only_cell_id(assignment)
        cell_root = read_only_cell_root(self._stack_root, assignment)
        workspace = cell_root / "workspace"
        home = cell_root / "home"
        codex_home = cell_root / "codex-home"
        source = cell_root / "source"

        # One cell per assignment (the runtime's phase-claim guard ensures a single
        # acquire), so a fresh directory must not already exist.
        cell_root.mkdir(parents=True, exist_ok=False)
        os.chmod(cell_root, _CELL_DIR_MODE)
        for directory in (home, codex_home, source):
            directory.mkdir()
            os.chmod(directory, _CELL_DIR_MODE)
        # The workspace is created writable, left EMPTY, then sealed read-only last
        # so its content can never change after the digest is taken.
        workspace.mkdir()
        os.chmod(workspace, _WORKSPACE_MODE)

        accounting = capture_directory(
            workspace, CODEX_WORKSPACE_LIMITS, reject_controls=True
        ).accounting
        projection = SanitizedWorkspaceProjection(
            source.as_posix(),
            workspace.as_posix(),
            accounting.digest,
            accounting.file_count,
            accounting.total_bytes,
        )
        profile = read_only_static_profile(self._model_id)
        compilation = compile_birth_policy(
            BirthPolicyRequest(
                profile.pin,
                selected_skills=(),
                requested_native_subagents=NativeSubagentLimits(),
            ),
            profile,
            (),
        )
        layout = validate_cell_layout(
            CodexCellLayout(
                assignment.phase.phase_id,
                cell_id,
                self._stack_root,
                cell_root,
                projection,
                home,
                codex_home,
            )
        )
        return CodexPhaseAdmission(
            assignment,
            layout,
            CodexWorkspaceProjectionBinding(assignment, projection),
            compilation,
            (),
            SkillAttestationPlan(workspace.as_posix(), (), generation=1),
            READ_ONLY_INSTRUCTIONS,
            compilation.policy.digest(),
        )


    def _provision_per_cell(
        self, assignment: PhaseAssignmentRef, slot: CellSlot
    ) -> CodexPhaseAdmission:
        """Assemble a slot-rooted admission WITHOUT touching the filesystem.

        Under per-cell uids the tree lives in the cell's own 0700 slot, owned by the
        cell uid (2000N), which this API process (uid 10001, no caps) can neither
        write nor traverse. So the source does no ``mkdir``/``capture`` here: it
        builds the layout with slot paths and the constant EMPTY-workspace
        projection, and defers the actual creation to the spawner (driven by the
        provider via ``provision_cell_tree``). ``validate_cell_layout`` runs every
        path-shape check but skips the local-ownership leg, which the spawner's child
        performs cell-uid-side.
        """

        cell_id = read_only_cell_id(assignment)
        cell_root = slot.root
        workspace = cell_root / "workspace"
        home = cell_root / "home"
        codex_home = cell_root / "codex-home"
        source = cell_root / "source"
        projection = SanitizedWorkspaceProjection(
            source.as_posix(),
            workspace.as_posix(),
            EMPTY_WORKSPACE_DIGEST,
            EMPTY_WORKSPACE_FILE_COUNT,
            EMPTY_WORKSPACE_TOTAL_BYTES,
        )
        profile = read_only_static_profile(self._model_id)
        compilation = compile_birth_policy(
            BirthPolicyRequest(
                profile.pin,
                selected_skills=(),
                requested_native_subagents=NativeSubagentLimits(),
            ),
            profile,
            (),
        )
        layout = validate_cell_layout(
            CodexCellLayout(
                assignment.phase.phase_id,
                cell_id,
                self._stack_root,
                cell_root,
                projection,
                home,
                codex_home,
            ),
            require_local_ownership=False,
        )
        return CodexPhaseAdmission(
            assignment,
            layout,
            CodexWorkspaceProjectionBinding(assignment, projection),
            compilation,
            (),
            SkillAttestationPlan(workspace.as_posix(), (), generation=1),
            READ_ONLY_INSTRUCTIONS,
            compilation.policy.digest(),
            slot_provisioned=True,
        )

    def cell_tree_manifest(
        self, layout: CodexCellLayout
    ) -> list[dict[str, object]]:
        """The directory manifest the spawner creates for a per-cell layout.

        home/codex-home/source at 0700, workspace at 0500 (empty, read-only). The
        provider hands this to ``provision_cell_tree``; the config.toml file is added
        separately by ``_write_cell_config`` once it is rendered.
        """

        return [
            {"path": layout.home.as_posix(), "mode": _CELL_DIR_MODE},
            {"path": layout.codex_home.as_posix(), "mode": _CELL_DIR_MODE},
            {"path": (layout.cell_root / "source").as_posix(), "mode": _CELL_DIR_MODE},
            {"path": layout.workspace.as_posix(), "mode": _WORKSPACE_MODE},
        ]


__all__ = ["ProvisioningCodexPhaseAdmissionSource"]
