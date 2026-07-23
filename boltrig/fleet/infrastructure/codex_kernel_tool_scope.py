"""The per-run kernel-tools scope: one run-scoped MCP token plus its ceiling.

The kernel-tools Codex lane hands the cell exactly one new capability: an
``[mcp_servers.boltrig]`` entry whose bearer is a RUN-SCOPED kernel MCP token
(the same ``McpFace.issue_run_token`` seam pi/opencode/rivet already use,
SEC-23). The token is minted adapter-side, where the invocation context (and
therefore the run's grants) lives, but CONSUMED provisioning-side, where the
cell's config and environment are built. This module is the hand-off: a
redacted, unpicklable scope value and a bounded pop-once registry keyed by
assignment id.

Token hygiene, matching the lane's doctrine:

  * the token NEVER appears in a repr, a digest, an event, or a config file -
    ``__repr__`` is redacted and pickling/copying is refused outright;
  * the registry is pop-once (``take`` removes the entry), so a token lives in
    the registry for exactly the admit window and a stale scope cannot be
    consumed twice;
  * revocation stays with the minter (the adapter revokes in ``finally``,
    exactly like ``PiRuntime``), and the adapter also ``discard``s any
    un-consumed scope, so a failed start cannot strand one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Never, SupportsIndex

from .codex_kernel_tools_phase import validated_kernel_tool_names
from .codex_runtime_config_policy import (
    CodexRuntimeConfigError,
    validate_mcp_server_url,
)

MAX_KERNEL_TOOL_SCOPES = 64
MAX_RUN_TOKEN_LENGTH = 512


class CodexKernelToolScopeError(ValueError):
    """A kernel-tools scope or registry value failed closed validation."""


@dataclass(frozen=True, repr=False, slots=True)
class CodexKernelToolScope:
    """One assignment's kernel-MCP delivery values; the token is a secret."""

    assignment_id: str
    mcp_url: str
    tools: tuple[str, ...]
    token: str

    def __post_init__(self) -> None:
        if (
            type(self.assignment_id) is not str
            or not self.assignment_id
            or self.assignment_id != self.assignment_id.strip()
            or any(ord(character) < 0x21 or ord(character) > 0x7E for character in self.assignment_id)
        ):
            raise CodexKernelToolScopeError("kernel tool scope assignment id is invalid")
        try:
            validate_mcp_server_url(self.mcp_url)
            object.__setattr__(self, "tools", validated_kernel_tool_names(self.tools))
        except (CodexRuntimeConfigError, ValueError) as error:
            raise CodexKernelToolScopeError(str(error)) from None
        if (
            type(self.token) is not str
            or not 1 <= len(self.token) <= MAX_RUN_TOKEN_LENGTH
            or any(ord(character) < 0x21 or ord(character) > 0x7E for character in self.token)
        ):
            raise CodexKernelToolScopeError("kernel tool scope token is invalid")

    def __repr__(self) -> str:
        return "CodexKernelToolScope(redacted=True)"

    def __reduce_ex__(self, _protocol: SupportsIndex) -> Never:
        raise TypeError("kernel tool scopes must not be pickled or copied")


class CodexKernelToolScopeRegistry:
    """A bounded, pop-once, assignment-keyed hand-off for live scopes."""

    def __init__(self) -> None:
        self._scopes: dict[str, CodexKernelToolScope] = {}

    def register(self, scope: CodexKernelToolScope) -> None:
        if type(scope) is not CodexKernelToolScope:
            raise TypeError("scope must be an exact CodexKernelToolScope")
        if scope.assignment_id in self._scopes:
            raise CodexKernelToolScopeError("kernel tool scope already registered")
        if len(self._scopes) >= MAX_KERNEL_TOOL_SCOPES:
            raise CodexKernelToolScopeError("kernel tool scope registry is full")
        self._scopes[scope.assignment_id] = scope

    def take(self, assignment_id: object) -> CodexKernelToolScope | None:
        """Pop the scope for ``assignment_id`` (None when none was registered)."""

        if type(assignment_id) is not str:
            raise TypeError("assignment id must be an exact string")
        return self._scopes.pop(assignment_id, None)

    def discard(self, assignment_id: object) -> None:
        """Drop an un-consumed scope without consuming it (failure cleanup)."""

        if type(assignment_id) is str:
            self._scopes.pop(assignment_id, None)

    def __len__(self) -> int:
        return len(self._scopes)


__all__ = [
    "MAX_KERNEL_TOOL_SCOPES",
    "CodexKernelToolScope",
    "CodexKernelToolScopeError",
    "CodexKernelToolScopeRegistry",
]
