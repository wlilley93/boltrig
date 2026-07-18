"""Tests for the read-only Codex cell provisioning admission source (#30).

Provisions a real cell in a tmp stack root and pins two things: the produced
admission is valid (fail-closed dir modes, read-only policy), and - the crux
integration contract - the adapter's deterministic spec passes ``validate_admission``
against the freshly-provisioned cell.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from boltrig.fleet.infrastructure.codex_cell_policy import validate_cell_layout
from boltrig.fleet.infrastructure.codex_cell_provisioning import (
    ProvisioningCodexPhaseAdmissionSource,
)
from boltrig.fleet.infrastructure.codex_read_only_phase import (
    read_only_thread_spec,
    read_only_workspace_path,
)
from boltrig.fleet.infrastructure.codex_runtime_admission import CodexPhaseAdmission
from boltrig.fleet.infrastructure.codex_runtime_validation import validate_admission
from tests.unit.codex_runtime_fakes import assignment, leased_cell


def _stack(tmp_path: Path) -> Path:
    stack = tmp_path / "codex-cells"
    stack.mkdir()
    os.chmod(stack, 0o700)
    return stack


def _mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


async def test_provisions_a_valid_read_only_admission(tmp_path: Path) -> None:
    source = ProvisioningCodexPhaseAdmissionSource(
        stack_root=_stack(tmp_path), model_id="glm-4.6"
    )
    a = assignment("prov")
    admission = await source.admit(a)

    assert type(admission) is CodexPhaseAdmission
    validate_cell_layout(admission.layout)  # re-validates fail-closed layout
    assert admission.layout.workspace == read_only_workspace_path(
        admission.layout.stack_root, a
    )
    assert _mode(admission.layout.workspace) == 0o500
    assert _mode(admission.layout.home) == 0o700
    assert _mode(admission.layout.codex_home) == 0o700

    policy = admission.compilation.policy
    assert policy.sandbox.value == "read_only"
    assert policy.enabled_tools == ()
    native = policy.native_subagents
    assert (native.max_total, native.max_concurrent, native.max_depth) == (0, 0, 0)
    # empty workspace -> the empty-directory digest, zero files/bytes
    assert admission.layout.workspace_projection.file_count == 0
    assert admission.layout.workspace_projection.total_bytes == 0


async def test_provisioned_admission_accepts_the_adapter_spec(tmp_path: Path) -> None:
    stack = _stack(tmp_path)
    source = ProvisioningCodexPhaseAdmissionSource(stack_root=stack, model_id="glm-4.6")
    a = assignment("match")
    admission = await source.admit(a)

    # The adapter builds this spec independently, before the cell exists; it must
    # match the provisioned admission exactly (workspace, profile, skills).
    spec = read_only_thread_spec(a, stack)
    leased, _fake = leased_cell(admission)
    validate_admission(spec, leased)  # raises on any mismatch
    assert spec.working_directory == admission.layout.workspace.as_posix()


async def test_second_acquire_of_the_same_assignment_is_rejected(tmp_path: Path) -> None:
    stack = _stack(tmp_path)
    source = ProvisioningCodexPhaseAdmissionSource(stack_root=stack, model_id="glm-4.6")
    a = assignment("dup")
    await source.admit(a)
    with pytest.raises(FileExistsError):
        await source.admit(a)


def test_rejects_a_relative_stack_root() -> None:
    with pytest.raises(Exception):
        ProvisioningCodexPhaseAdmissionSource(
            stack_root=Path("relative/cells"), model_id="glm-4.6"
        )


def test_rejects_a_blank_model_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        ProvisioningCodexPhaseAdmissionSource(stack_root=_stack(tmp_path), model_id="  ")
