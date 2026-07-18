"""The shared read-only Codex phase contract (adapter <-> admission source).

``validate_admission`` (codex_runtime_validation.py) requires the thread spec the
adapter builds to match the provisioned admission EXACTLY on three axes: the
working directory (the admitted workspace), the profile (name+version), and the
selected skills. The adapter builds its spec BEFORE the provider provisions the
cell, so all three must be DETERMINISTIC from the assignment. This module is the
one place both sides derive them, so they cannot drift:

  * the fixed read-only ``ProfileRef`` (no tools, no skills, no native subagents),
  * a deterministic per-assignment cell/workspace path under a stack root, and
  * the exact read-only ``RuntimeThreadSpec`` the adapter sends.

The provisioning admission source (codex_cell_provisioning.py) provisions the
cell at ``read_only_cell_root`` and compiles ``read_only_static_profile``; the
adapter (fleet.codex_runtime) sends ``read_only_thread_spec`` for the same
assignment. Each assignment is acquired at most once (the runtime's phase-claim
guard), so a deterministic per-assignment path never collides in practice.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from boltrig.fleet.domain import (
    PhaseAssignmentRef,
    ProfileRef,
    SandboxPolicy,
)
from boltrig.fleet.domain.profile_policy import StaticRoleProfile
from boltrig.fleet.domain.profile_policy_values import (
    DigestPinnedContent,
    ExactModelPolicy,
    NativeSubagentLimits,
    NativeSubagentPolicy,
    ReasoningEffort,
    RuntimeToolPolicy,
)
from boltrig.fleet.ports.runtime import RuntimeThreadSpec

READ_ONLY_PROFILE_NAME = "codex-read-only"
READ_ONLY_PROFILE_VERSION = "1.0.0"
READ_ONLY_PROFILE = ProfileRef(READ_ONLY_PROFILE_NAME, READ_ONLY_PROFILE_VERSION)

# The bounded read-only birth instructions. Kept short and pinned; the same text
# is compiled into the birth policy (its digest binds the profile) and passed to
# ``thread_start`` as developer instructions.
READ_ONLY_INSTRUCTIONS = (
    "You are a bounded, read-only Boltrig phase. Reason over the provided task "
    "and report only verified conclusions. You have no tools and cannot write, "
    "run commands, or spawn subagents."
)


def _sha256(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def read_only_cell_id(assignment: PhaseAssignmentRef) -> str:
    """A deterministic, control-free cell id for an assignment.

    Deterministic so the adapter and the provisioner agree on the workspace path
    without a round trip; a digest of the assignment id keeps it opaque and safe.
    """
    tag = hashlib.sha256(assignment.assignment_id.encode("utf-8")).hexdigest()[:16]
    return f"cell-{tag}"


def read_only_cell_root(stack_root: Path, assignment: PhaseAssignmentRef) -> Path:
    return stack_root / "cells" / read_only_cell_id(assignment)


def read_only_workspace_path(stack_root: Path, assignment: PhaseAssignmentRef) -> Path:
    return read_only_cell_root(stack_root, assignment) / "workspace"


def read_only_thread_spec(
    assignment: PhaseAssignmentRef, stack_root: Path
) -> RuntimeThreadSpec:
    """The exact read-only spec the adapter sends for ``assignment``.

    Matches the provisioned admission by construction: the fixed read-only
    profile, no skills, and the deterministic admitted workspace as the cwd.
    """
    return RuntimeThreadSpec(
        assignment=assignment,
        profile=READ_ONLY_PROFILE,
        skills=(),
        working_directory=read_only_workspace_path(stack_root, assignment).as_posix(),
    )


def read_only_static_profile(model_id: str) -> StaticRoleProfile:
    """The read-only static profile compiled into the birth policy.

    No tools, no skills, native subagents disabled, read-only sandbox default and
    ceiling. ``model_id`` is the model the cell requests from its per-cell proxy;
    it does not appear in the thread spec, so it never has to be derived adapter-side.
    """
    return StaticRoleProfile(
        READ_ONLY_PROFILE_NAME,
        READ_ONLY_PROFILE_VERSION,
        DigestPinnedContent(
            f"profiles/{READ_ONLY_PROFILE_NAME}/{READ_ONLY_PROFILE_VERSION}/instructions.md",
            _sha256(READ_ONLY_INSTRUCTIONS),
        ),
        ExactModelPolicy(model_id, ReasoningEffort.HIGH),
        RuntimeToolPolicy((), ()),
        SandboxPolicy.READ_ONLY,
        SandboxPolicy.READ_ONLY,
        (),
        NativeSubagentPolicy(NativeSubagentLimits(), NativeSubagentLimits()),
    )


__all__ = [
    "READ_ONLY_INSTRUCTIONS",
    "READ_ONLY_PROFILE",
    "READ_ONLY_PROFILE_NAME",
    "READ_ONLY_PROFILE_VERSION",
    "read_only_cell_id",
    "read_only_cell_root",
    "read_only_static_profile",
    "read_only_thread_spec",
    "read_only_workspace_path",
]
