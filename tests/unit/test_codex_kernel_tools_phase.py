"""Unit tests for the kernel-tools Codex phase contract and the scope hand-off.

The claims pinned here:

  * the wire-name rule replicates Codex 0.144.3's
    ``sanitize_responses_api_tool_name`` exactly (dots, dashes and any other
    non-``[a-zA-Z0-9_]`` character become ``_``; case is preserved), and the
    model-facing name is the NESTED name inside the ``mcp__boltrig`` namespace
    (verified live against the pinned binary), so the admission ceiling is
    byte-identical to what the model wire carries;
  * the ceiling validator is fail-closed: exact tuple of exact bounded names,
    unique, bounded, sorted;
  * the kernel-tools profile keeps the wall: read-only sandbox default and
    ceiling, no native tools, no native subagents, no skills;
  * the scope is a redacted, unpicklable secret container, and the registry is
    bounded and pop-once.
"""

from __future__ import annotations

import pickle
from pathlib import Path

import pytest

from boltrig.fleet.infrastructure.codex_kernel_tool_scope import (
    MAX_KERNEL_TOOL_SCOPES,
    CodexKernelToolScope,
    CodexKernelToolScopeError,
    CodexKernelToolScopeRegistry,
)
from boltrig.fleet.infrastructure.codex_kernel_tools_phase import (
    CODEX_MCP_NAMESPACE_NAME,
    KERNEL_TOOLS_INSTRUCTIONS,
    KERNEL_TOOLS_PROFILE,
    KERNEL_TOOLS_PROFILE_NAME,
    KERNEL_TOOLS_PROFILE_VERSION,
    MAX_KERNEL_TOOLS,
    CodexKernelToolsError,
    codex_mcp_tool_name,
    kernel_tools_static_profile,
    kernel_tools_thread_spec,
    validated_kernel_tool_names,
)
from boltrig.fleet.infrastructure.codex_read_only_phase import (
    read_only_workspace_path,
)
from boltrig.fleet.domain import PhaseMode, SandboxPolicy

from .codex_runtime_fakes import assignment


def test_wire_name_replicates_the_codex_sanitizer() -> None:
    assert CODEX_MCP_NAMESPACE_NAME == "mcp__boltrig"
    assert codex_mcp_tool_name("ticket.read") == "ticket_read"
    assert codex_mcp_tool_name("ms-graph.sendMail") == "ms_graph_sendMail"
    # Non-ASCII collapses to "_" (Codex keeps ASCII alphanumerics only).
    assert codex_mcp_tool_name("café.run") == "caf__run"


@pytest.mark.parametrize("verb_id", ["", 1, None])
def test_wire_name_refuses_a_bad_verb_id(verb_id: object) -> None:
    with pytest.raises(CodexKernelToolsError):
        codex_mcp_tool_name(verb_id)  # type: ignore[arg-type]


def test_validated_kernel_tools_are_exact_unique_bounded_and_sorted() -> None:
    names = ("tool_b", "tool_a")
    assert validated_kernel_tool_names(names) == ("tool_a", "tool_b")
    assert validated_kernel_tool_names(()) == ()


@pytest.mark.parametrize(
    "values",
    [
        ["tool_a"],  # not a tuple
        ("tool.a",),  # unsanitized
        ("tool_a", "tool_a"),  # duplicate
        ("tool_a", 1),  # non-string member
        ("has space",),
        tuple(f"tool_{i}" for i in range(MAX_KERNEL_TOOLS + 1)),
    ],
)
def test_validated_kernel_tools_fail_closed(values: object) -> None:
    with pytest.raises(CodexKernelToolsError):
        validated_kernel_tool_names(values)


def test_kernel_tools_profile_keeps_the_read_only_wall() -> None:
    profile = kernel_tools_static_profile("gpt-5.4")
    assert (profile.name, profile.version) == (
        KERNEL_TOOLS_PROFILE_NAME,
        KERNEL_TOOLS_PROFILE_VERSION,
    )
    assert profile.tools.defaults == () and profile.tools.ceiling == ()
    assert profile.default_sandbox is SandboxPolicy.READ_ONLY
    assert profile.sandbox_ceiling is SandboxPolicy.READ_ONLY
    assert profile.permitted_skills == ()
    limits = profile.native_subagents
    assert (limits.ceiling.max_total, limits.ceiling.max_depth) == (0, 0)


def test_kernel_tools_thread_spec_matches_the_provisioned_lane() -> None:
    value = assignment("kt")
    spec = kernel_tools_thread_spec(value, Path("/stack"))
    assert spec.profile == KERNEL_TOOLS_PROFILE
    assert spec.skills == ()
    assert spec.mode is PhaseMode.READ_ONLY
    assert spec.sandbox is SandboxPolicy.READ_ONLY
    assert spec.working_directory == read_only_workspace_path(
        Path("/stack"), value
    ).as_posix()
    # The instructions are pinned into the profile digest.
    assert KERNEL_TOOLS_INSTRUCTIONS.strip() == KERNEL_TOOLS_INSTRUCTIONS


def _scope(**overrides: object) -> CodexKernelToolScope:
    values: dict[str, object] = {
        "assignment_id": "run-1-codex-assignment",
        "mcp_url": "http://kernel:8000/v1/mcp",
        "tools": ("ticket_read",),
        "token": "run-token-secret",
    }
    values.update(overrides)
    return CodexKernelToolScope(**values)  # type: ignore[arg-type]


def test_scope_is_redacted_and_unpicklable() -> None:
    scope = _scope()
    assert "run-token-secret" not in repr(scope)
    assert "http://kernel:8000" not in repr(scope)
    with pytest.raises(TypeError):
        pickle.dumps(scope)


@pytest.mark.parametrize(
    "override",
    [
        {"assignment_id": "  "},
        {"mcp_url": "http://user:pw@kernel:8000/v1/mcp"},  # credentials in a URL
        {"mcp_url": "ftp://kernel:8000/v1/mcp"},
        {"mcp_url": "http://kernel:8000/v1/mcp?x=1"},
        {"tools": ("bad.name",)},
        {"token": ""},
        {"token": "has space"},
    ],
)
def test_scope_validation_fails_closed(override: dict[str, object]) -> None:
    with pytest.raises(CodexKernelToolScopeError):
        _scope(**override)


def test_registry_is_bounded_and_pop_once() -> None:
    registry = CodexKernelToolScopeRegistry()
    scope = _scope()
    registry.register(scope)
    with pytest.raises(CodexKernelToolScopeError, match="already registered"):
        registry.register(scope)
    assert registry.take(scope.assignment_id) is scope
    assert registry.take(scope.assignment_id) is None  # pop-once
    registry.register(scope)
    registry.discard(scope.assignment_id)
    assert len(registry) == 0
    for index in range(MAX_KERNEL_TOOL_SCOPES):
        registry.register(_scope(assignment_id=f"assignment-{index}"))
    with pytest.raises(CodexKernelToolScopeError, match="full"):
        registry.register(_scope(assignment_id="one-too-many"))
