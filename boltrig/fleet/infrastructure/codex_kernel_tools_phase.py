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
  * the per-run tool ceiling as exact Codex NESTED tool names (the sanitized
    verb ids the ``mcp__boltrig`` namespace carries), which travel on
    ``CodexPhaseAdmission.kernel_tools`` rather than through the domain's
    ``enabled_tools`` - governed catalogue names cannot represent them
    (they carry uppercase), and
  * the exact ``RuntimeThreadSpec`` the adapter sends.

The wire-name rule REPLICATES Codex 0.144.3's ``sanitize_responses_api_tool_name``
(verified live against the pinned binary): codex offers the server as ONE
``{"type": "namespace", "name": "mcp__boltrig"}`` entry whose nested function
tools are the verb ids with every character outside ``[a-zA-Z0-9_]`` replaced by
``_``. The per-cell model proxy holds its ceiling in exactly these names, so
what the admission compiles is byte-identical to what the wire carries.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

from boltrig.addons import Addon, active_addons, composed_version
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
from boltrig.fleet.prompt_stack import compose_tool_harness

from .codex_read_only_phase import (
    read_only_cell_id,
    read_only_cell_root,
    read_only_workspace_path,
)
from .codex_runtime_config_toml import CODEX_MCP_SERVER_NAME


def _sha256(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


KERNEL_TOOLS_PROFILE_NAME = "codex-kernel-tools"

# The base version of the birth instructions. 1.0.0 was four sentences that named
# the wall and nothing else; 1.1.0 adds the governance floor and the tool-call
# harness (see ``fleet/prompt_stack``), because the lane that ships to clients was
# the ONLY lane that never sent the floor - including the sentence that explains
# the <untrusted> envelope its own chat path wraps user input in. 1.2.0 adds the
# memory rule that 1.1.0 left out on a premise which turned out to be false when
# checked against the live tenant rather than asserted. 1.3.0 adds the stable
# inspect/act/verify operating method and explicitly treats tool metadata as data,
# not a second instruction channel. 1.4.0 adds clean-room capability guidance for
# specialised tools, files/code, sourced research, and bounded delegation.
KERNEL_TOOLS_BASE_VERSION = "1.4.0"

# The lane's own wall statement. Everything else in the instructions is shared
# with any other tool-calling lane; this sentence is what makes it THIS lane.
KERNEL_TOOLS_LANE_FRAME = (
    "You are a bounded Boltrig phase. You may call only the boltrig MCP tools "
    "advertised to you. You cannot write files, run commands, or spawn subagents."
)


def kernel_tools_instructions(addons: tuple[Addon, ...] = ()) -> str:
    """The birth instructions for this lane, composed with any active addons."""

    return "\n\n".join(
        [
            KERNEL_TOOLS_LANE_FRAME,
            compose_tool_harness(tuple(addon.harness for addon in addons)),
        ]
    )


# Resolved ONCE at import: the birth policy is an attested artefact, so the text
# and the version a process compiles must not change under it mid-life. Both
# derive from the same ``_ACTIVE_ADDONS`` tuple, and the adapter and the admission
# both read these constants, so the two sides cannot drift - the same
# cannot-drift property this module's docstring claims for the tool ceiling.
#
# The version COMPOSES rather than forks: one profile name, with the active
# addons as semver build metadata (``1.1.0+opbox-1.0.0``). Adding an integration
# moves the pin forward instead of creating a second lineage to maintain.
_ACTIVE_ADDONS = active_addons()
KERNEL_TOOLS_PROFILE_VERSION = composed_version(KERNEL_TOOLS_BASE_VERSION, _ACTIVE_ADDONS)
KERNEL_TOOLS_PROFILE = ProfileRef(KERNEL_TOOLS_PROFILE_NAME, KERNEL_TOOLS_PROFILE_VERSION)
KERNEL_TOOLS_INSTRUCTIONS = kernel_tools_instructions(_ACTIVE_ADDONS)

# One server's tools is a bounded set: the ceiling is the run's effective verbs,
# and a run carrying more than this cannot be attested exactly, so it degrades
# rather than silently truncating the ceiling.
MAX_KERNEL_TOOLS = 128
MAX_KERNEL_TOOL_NAME_LENGTH = 128
_WIRE_NAME = re.compile(r"[A-Za-z0-9_]+\Z")

# The model-facing NAMESPACE the server appears under in the Responses payload
# (verified live against the pinned 0.144.3 binary): codex exposes the server as
# ``{"type": "namespace", "name": "mcp__boltrig", "tools": [...]}`` with the
# individual verbs as nested function tools named by ``codex_mcp_tool_name``.
CODEX_MCP_NAMESPACE_NAME = f"mcp__{CODEX_MCP_SERVER_NAME}"


class CodexKernelToolsError(ValueError):
    """A kernel-tools lane value is not an exact, bounded, canonical value."""


def _sanitize(value: str) -> str:
    """Replicate Codex 0.144.3's ``sanitize_responses_api_tool_name`` exactly."""

    return "".join(
        character if character.isascii() and (character.isalnum() or character == "_") else "_"
        for character in value
    )


def codex_mcp_tool_name(verb_id: str) -> str:
    """The exact model-facing NESTED tool name for a kernel verb.

    Verified live against the pinned binary: inside the ``mcp__boltrig``
    namespace the verb ``knowledge.search`` appears as the nested function tool
    ``knowledge_search`` - the sanitizer applied to the raw verb id, with no
    prefix. The proxy ceiling, the admission and the preflight attestation all
    derive names through this one function so they can never disagree.
    """

    if type(verb_id) is not str or not verb_id:
        raise CodexKernelToolsError("kernel tool verb id must be a non-empty string")
    return _sanitize(verb_id)


_log = logging.getLogger(__name__)


def admissible_kernel_tool_names(
    verb_ids: tuple[str, ...], *, run_id: str | None
) -> tuple[str, ...] | None:
    """The tool set ``validated_kernel_tool_names`` admits under
    ``MAX_KERNEL_TOOLS``, or None = the caller runs the read-only phase.

    None on BOTH inadmissible states, each logged with its own reason:

    OVER THE BOUND - a real deployment state, not a hypothetical: a tenant
    ceiling of allow:["*"] over a kernel registering 164 verbs met the 128
    bound on 2026-08-20, and because the named-agent lane forces kernel tools
    on every interactive turn, EVERY chat turn on that deployment degraded.
    The bound cannot move (it is the attestation cap) and the set must not be
    silently truncated (which 128 of 164 would be a policy choice nobody
    made), so the turn keeps its voice and loses its hands.

    EMPTY - a turn whose role loads no skills has no MCP face to offer;
    exactly what the legacy lanes did with empty grants. Observable, never
    silent, in both cases.
    """

    names = tuple({codex_mcp_tool_name(verb_id) for verb_id in verb_ids})
    if len(names) > MAX_KERNEL_TOOLS:
        _log.warning(
            "codex kernel-tools run %s compiled %d tools over the "
            "attestation bound of %d; falling back to the read-only phase",
            run_id, len(names), MAX_KERNEL_TOOLS,
        )
        return None
    tools = validated_kernel_tool_names(names)
    if not tools:
        _log.warning(
            "codex kernel-tools run %s has no effective tools; "
            "falling back to the read-only phase",
            run_id,
        )
        return None
    return tools


def validated_kernel_tool_names(values: object) -> tuple[str, ...]:
    """Canonicalize the per-run wire-name ceiling, fail-closed.

    Exact tuple of exact strings, each a bounded nested tool name, unique and
    sorted, within the count bound. Anything else is refused: the ceiling is a
    security value, so a malformed one is never "cleaned up".
    """

    if type(values) is not tuple or any(type(item) is not str for item in values):
        raise CodexKernelToolsError("kernel tools must be an exact tuple of strings")
    if len(values) > MAX_KERNEL_TOOLS:
        # The counts, because this is a CLIFF and the bare sentence gave an operator
        # nothing to act on. Measured on a live tenant: 197 verbs registered and a
        # tenant ceiling of allow:["*"], so a run whose grants resolve to the
        # wildcard is 197 against a bound of 128 and EVERY turn dies here. Skills
        # narrow it to ~74 today, which is the only reason it does not bite.
        # Two integers, no names: a count is not content (K-20).
        raise CodexKernelToolsError(
            f"kernel tools exceed the attestation bound: {len(values)} > {MAX_KERNEL_TOOLS}"
        )
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


def kernel_tools_thread_spec(assignment: PhaseAssignmentRef, stack_root: Path) -> RuntimeThreadSpec:
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
    "CODEX_MCP_NAMESPACE_NAME",
    "KERNEL_TOOLS_INSTRUCTIONS",
    "KERNEL_TOOLS_PROFILE",
    "KERNEL_TOOLS_PROFILE_NAME",
    "KERNEL_TOOLS_PROFILE_VERSION",
    "MAX_KERNEL_TOOLS",
    "admissible_kernel_tool_names",
    "MAX_KERNEL_TOOL_NAME_LENGTH",
    "CodexKernelToolsError",
    "codex_mcp_tool_name",
    "kernel_tools_cell_id",
    "kernel_tools_cell_root",
    "kernel_tools_static_profile",
    "kernel_tools_thread_spec",
    "validated_kernel_tool_names",
]
