"""The kernel-tools Codex phase contract (adapter <-> admission source).

Parallel to ``codex_read_only_phase``: the read-only lane reasons with NO tools,
while this lane may call BOLTRIG verbs through the kernel's MCP face - and only
through it. The cell wall is unchanged: the sandbox stays read-only, Codex's own
approval plane stays ``never`` (the kernel's HITL gate owns consequence), native
tools and subagents stay stripped, and the ONLY new capability is one
``[mcp_servers.boltrig]`` entry whose bearer is a run-scoped kernel token.

Both sides derive the same values from the assignment, exactly as the read-only
lane does, so the adapter's thread spec and the provisioned admission cannot
drift:

  * the fixed kernel-tools ``ProfileRef`` (no NATIVE tools - the domain birth
    policy stays tool-free, because kernel tools are not Codex runtime tools and
    are governed at the kernel chokepoint, not by the runtime),
  * the per-run tool ceiling as exact Codex WIRE names (``mcp__boltrig__*``),
    which travel on ``CodexPhaseAdmission.kernel_tools`` rather than through the
    domain's ``enabled_tools`` - governed catalogue names cannot represent them
    (they carry uppercase and the ``mcp__`` double underscore), and
  * the exact ``RuntimeThreadSpec`` the adapter sends.

The wire-name rule REPLICATES Codex 0.144.3's ``sanitize_responses_api_tool_name``
(verified against the tagged source): the model-facing name is
``mcp__<server>__<tool>`` with every character outside ``[a-zA-Z0-9_]`` replaced
by ``_``. The per-cell model proxy holds its ceiling in exactly these names, so
what the admission compiles is byte-identical to what the wire carries.
"""

from __future__ import annotations

import hashlib
import re
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

from .codex_read_only_phase import (
    read_only_cell_id,
    read_only_cell_root,
    read_only_workspace_path,
)
from .codex_runtime_config_toml import CODEX_MCP_SERVER_NAME


def _sha256(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"

KERNEL_TOOLS_PROFILE_NAME = "codex-kernel-tools"
KERNEL_TOOLS_PROFILE_VERSION = "1.0.0"
KERNEL_TOOLS_PROFILE = ProfileRef(KERNEL_TOOLS_PROFILE_NAME, KERNEL_TOOLS_PROFILE_VERSION)

# The bounded kernel-tools birth instructions. Same discipline as the read-only
# text: short, pinned, compiled into the birth policy and passed to
# ``thread_start`` verbatim.
KERNEL_TOOLS_INSTRUCTIONS = (
    "You are a bounded Boltrig phase. You may call only the boltrig MCP tools "
    "advertised to you; every call is mediated by the kernel, which may deny it "
    "or hold it for human approval. You cannot write files, run commands, or "
    "spawn subagents. Report only verified conclusions."
)

# One server's tools is a bounded set: the ceiling is the run's effective verbs,
# and a run carrying more than this cannot be attested exactly, so it degrades
# rather than silently truncating the ceiling.
MAX_KERNEL_TOOLS = 128
MAX_KERNEL_TOOL_NAME_LENGTH = 128
_WIRE_NAME = re.compile(r"mcp__boltrig__[A-Za-z0-9_]+\Z")


class CodexKernelToolsError(ValueError):
    """A kernel-tools lane value is not an exact, bounded, canonical value."""


def codex_mcp_wire_name(verb_id: str) -> str:
    """The exact Codex 0.144.3 model-facing name for a kernel MCP tool.

    Replicates ``sanitize_responses_api_tool_name`` over
    ``mcp__<server>__<tool>``: ASCII alphanumerics and ``_`` survive, every
    other character becomes ``_`` (case is preserved). The proxy ceiling, the
    admission and the preflight attestation all derive names through this one
    function so the three can never disagree about the mapping.
    """

    if type(verb_id) is not str or not verb_id:
        raise CodexKernelToolsError("kernel tool verb id must be a non-empty string")
    raw = f"mcp__{CODEX_MCP_SERVER_NAME}__{verb_id}"
    return "".join(
        character
        if character.isascii() and (character.isalnum() or character == "_")
        else "_"
        for character in raw
    )


def validated_kernel_tool_names(values: object) -> tuple[str, ...]:
    """Canonicalize the per-run wire-name ceiling, fail-closed.

    Exact tuple of exact strings, each a bounded ``mcp__boltrig__*`` wire name,
    unique and sorted, within the count bound. Anything else is refused: the
    ceiling is a security value, so a malformed one is never "cleaned up".
    """

    if type(values) is not tuple or any(type(item) is not str for item in values):
        raise CodexKernelToolsError("kernel tools must be an exact tuple of strings")
    if len(values) > MAX_KERNEL_TOOLS:
        raise CodexKernelToolsError("kernel tools exceed the attestation bound")
    for name in values:
        if len(name) > MAX_KERNEL_TOOL_NAME_LENGTH or _WIRE_NAME.fullmatch(name) is None:
            raise CodexKernelToolsError("kernel tool name is not an exact boltrig wire name")
    if len(set(values)) != len(values):
        raise CodexKernelToolsError("kernel tools must be unique")
    return tuple(sorted(values))


def kernel_tools_cell_id(assignment: PhaseAssignmentRef) -> str:
    """The same deterministic per-assignment cell id scheme as the read-only lane."""

    return read_only_cell_id(assignment)


def kernel_tools_cell_root(stack_root: Path, assignment: PhaseAssignmentRef) -> Path:
    return read_only_cell_root(stack_root, assignment)


def kernel_tools_thread_spec(
    assignment: PhaseAssignmentRef, stack_root: Path
) -> RuntimeThreadSpec:
    """The exact kernel-tools spec the adapter sends for ``assignment``.

    Matches the provisioned admission by construction: the fixed kernel-tools
    profile, no skills, and the deterministic admitted workspace as the cwd. The
    tool ceiling itself travels on the admission (and the scope registry), never
    on the spec.
    """

    return RuntimeThreadSpec(
        assignment=assignment,
        profile=KERNEL_TOOLS_PROFILE,
        skills=(),
        working_directory=read_only_workspace_path(stack_root, assignment).as_posix(),
    )


def kernel_tools_static_profile(model_id: str) -> StaticRoleProfile:
    """The kernel-tools static profile compiled into the birth policy.

    No NATIVE tools (the domain policy stays tool-free: kernel tools are MCP
    tools governed at the kernel chokepoint, not Codex runtime tools), no
    skills, native subagents disabled, read-only sandbox default and ceiling.
    """

    return StaticRoleProfile(
        KERNEL_TOOLS_PROFILE_NAME,
        KERNEL_TOOLS_PROFILE_VERSION,
        DigestPinnedContent(
            f"profiles/{KERNEL_TOOLS_PROFILE_NAME}/{KERNEL_TOOLS_PROFILE_VERSION}/instructions.md",
            _sha256(KERNEL_TOOLS_INSTRUCTIONS),
        ),
        ExactModelPolicy(model_id, ReasoningEffort.HIGH),
        RuntimeToolPolicy((), ()),
        SandboxPolicy.READ_ONLY,
        SandboxPolicy.READ_ONLY,
        (),
        NativeSubagentPolicy(NativeSubagentLimits(), NativeSubagentLimits()),
    )


__all__ = [
    "KERNEL_TOOLS_INSTRUCTIONS",
    "KERNEL_TOOLS_PROFILE",
    "KERNEL_TOOLS_PROFILE_NAME",
    "KERNEL_TOOLS_PROFILE_VERSION",
    "MAX_KERNEL_TOOLS",
    "MAX_KERNEL_TOOL_NAME_LENGTH",
    "CodexKernelToolsError",
    "codex_mcp_wire_name",
    "kernel_tools_cell_id",
    "kernel_tools_cell_root",
    "kernel_tools_static_profile",
    "kernel_tools_thread_spec",
    "validated_kernel_tool_names",
]
