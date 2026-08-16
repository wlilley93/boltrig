"""Validated non-secret wiring for the Codex kernel-tools lane."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from boltrig.fleet.infrastructure.codex_kernel_tool_scope import (
    CodexKernelToolScopeRegistry,
)
from boltrig.fleet.infrastructure.codex_runtime_config_policy import (
    CodexRuntimeConfigError,
    validate_mcp_server_url,
)
from boltrig.models import GrantSet

DEFAULT_KERNEL_TOOLS_TOKEN_TTL_SECONDS = 3600
TokenIssuer = Callable[..., str]
ToolCeilingCompiler = Callable[[str, GrantSet], Awaitable[tuple[str, ...]]]


@dataclass(frozen=True, repr=False, slots=True)
class CodexKernelToolWiring:
    """The kernel-tools lane's injected seams; carries no secret material."""

    issue_token: TokenIssuer
    revoke_token: Callable[[str], None]
    compile_tool_ceiling: ToolCeilingCompiler
    mcp_url: str
    registry: CodexKernelToolScopeRegistry
    ttl_seconds: int = DEFAULT_KERNEL_TOOLS_TOKEN_TTL_SECONDS

    def __post_init__(self) -> None:
        if not callable(self.issue_token) or not callable(self.revoke_token):
            raise TypeError("kernel tool wiring token callables are required")
        if not callable(self.compile_tool_ceiling):
            raise TypeError("kernel tool wiring requires a tool ceiling compiler")
        try:
            validate_mcp_server_url(self.mcp_url)
        except CodexRuntimeConfigError as error:
            raise ValueError(str(error)) from None
        if type(self.registry) is not CodexKernelToolScopeRegistry:
            raise TypeError("registry must be an exact CodexKernelToolScopeRegistry")
        if type(self.ttl_seconds) is not int or not 1 <= self.ttl_seconds <= 3600:
            raise ValueError("kernel tool token TTL must be between 1 and 3600 seconds")

    def __repr__(self) -> str:
        return "CodexKernelToolWiring(redacted=True)"


__all__ = [
    "CodexKernelToolWiring",
    "DEFAULT_KERNEL_TOOLS_TOKEN_TTL_SECONDS",
]
