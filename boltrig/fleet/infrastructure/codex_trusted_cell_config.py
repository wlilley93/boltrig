"""Cell-local configuration helpers for the trusted Codex provider."""

from __future__ import annotations

import os
from pathlib import Path

from boltrig.fleet.domain import NativeSubagentLimits
from boltrig.fleet.infrastructure.cell_slots import CellSlot
from boltrig.fleet.infrastructure.codex_cell_boundary import CellIsolationBoundary
from boltrig.fleet.infrastructure.codex_cell_policy import CodexCellLayout
from boltrig.fleet.infrastructure.codex_cell_supervisor import CodexCellSupervisor
from boltrig.fleet.infrastructure.codex_kernel_tool_scope import CodexKernelToolScope
from boltrig.fleet.infrastructure.codex_runtime_config import (
    CodexReasoningEffort,
    ComposedCodexRuntimeConfig,
)
from boltrig.fleet.infrastructure.codex_runtime_config_toml import (
    CODEX_MCP_BEARER_ENV_VAR,
)
from boltrig.fleet.infrastructure.codex_trusted_proxy_support import (
    model_policy_digest,
    render_trusted_config,
    write_cell_config,
)


def kernel_tools_environment(
    kernel_scope: CodexKernelToolScope | None,
) -> dict[str, str] | None:
    """``kernel_tools_environment`` carries the run-scoped MCP bearer.

    Never the config file (G3: sibling-writable), never argv (world-readable to
    a sibling); the read-only lane passes None and spawns byte-identically.
    """

    if kernel_scope is None:
        return None
    return {CODEX_MCP_BEARER_ENV_VAR: kernel_scope.token}


def _expected_cell_credentials(slot: CellSlot | None) -> tuple[int, int]:
    """Return allocated credentials, never credentials asserted by the child."""

    if slot is None:
        return os.getuid(), os.getgid()
    return slot.uid, slot.gid


def per_cell_tree_dirs(layout: CodexCellLayout) -> list[dict[str, object]]:
    """Describe the cell-owned tree provisioned by the privileged spawner."""

    return [
        {"path": layout.home.as_posix(), "mode": 0o700},
        {"path": layout.codex_home.as_posix(), "mode": 0o700},
        {"path": (layout.cell_root / "source").as_posix(), "mode": 0o700},
        {"path": layout.workspace.as_posix(), "mode": 0o500},
    ]


async def compose_and_write_cell_config(
    *,
    supervisor: CodexCellSupervisor,
    boundary: CellIsolationBoundary,
    reasoning_effort: CodexReasoningEffort,
    cell_id: str,
    cell_root: Path,
    codex_home: Path,
    model_id: str,
    proxy_port: int,
    socket_name: str,
    native_subagents: NativeSubagentLimits = NativeSubagentLimits(),
    slot: CellSlot | None = None,
    tree_dirs: list[dict[str, object]] | None = None,
    kernel_scope: CodexKernelToolScope | None = None,
) -> ComposedCodexRuntimeConfig:
    """Render once, persist once, and return the exact preflight receipt source."""

    composed = render_trusted_config(
        cell_id=cell_id,
        cell_root=cell_root,
        codex_home=codex_home,
        helper_path=boundary.helper_path,
        helper_sha256=boundary.helper_sha256,
        socket_name=socket_name,
        model_id=model_id,
        policy_digest=model_policy_digest(model_id, reasoning_effort),
        reasoning_effort=reasoning_effort,
        proxy_port=proxy_port,
        native_subagents=native_subagents,
        mcp_server_url=None if kernel_scope is None else kernel_scope.mcp_url,
        mcp_bearer_env_var=(None if kernel_scope is None else CODEX_MCP_BEARER_ENV_VAR),
    )
    if slot is not None:
        await supervisor.provision_cell_tree(
            slot,
            dirs=tree_dirs or [],
            files=[
                {
                    "path": (codex_home / "config.toml").as_posix(),
                    "mode": 0o600,
                    "content": composed.config_toml,
                }
            ],
        )
    else:
        write_cell_config(codex_home, composed.config_toml)
    return composed


__all__ = [
    "compose_and_write_cell_config",
    "_expected_cell_credentials",
    "kernel_tools_environment",
    "per_cell_tree_dirs",
]
