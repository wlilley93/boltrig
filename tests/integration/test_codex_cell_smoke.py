from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest

from boltrig.fleet.infrastructure.codex_cell_policy import CodexCellLayout
from boltrig.fleet.infrastructure.codex_cell_supervisor import CodexCellSupervisor
from boltrig.fleet.infrastructure.codex_runtime_config_argv import (
    codex_app_server_arguments,
)
from boltrig.fleet.infrastructure.codex_runtime_config_toml import (
    codex_runtime_features,
)
from tests.unit.codex_process_fakes import pinned_arguments
from boltrig.fleet.infrastructure.skill_artifacts import SanitizedWorkspaceProjection

_BINARY_ENV = "BOLTRIG_CODEX_01443_SMOKE_BINARY"


def _empty_layout(tmp_path: Path, *, suffix: str) -> CodexCellLayout:
    stack = tmp_path / "stack"
    cell_id = f"cell-{suffix}"
    cell_root = stack / cell_id
    workspace = cell_root / "workspace"
    home = cell_root / "home"
    codex_home = cell_root / "codex-home"
    for directory in (stack, cell_root, workspace, home, codex_home):
        directory.mkdir(exist_ok=True)
        directory.chmod(0o700)
    workspace.chmod(0o500)
    return CodexCellLayout(
        phase_id=f"phase-{suffix}",
        cell_id=cell_id,
        stack_root=stack,
        cell_root=cell_root,
        workspace_projection=SanitizedWorkspaceProjection(
            source_path=(tmp_path / "empty-source").as_posix(),
            workspace_path=workspace.as_posix(),
            workspace_digest="sha256:" + hashlib.sha256(b"").hexdigest(),
            file_count=0,
            total_bytes=0,
        ),
        home=home,
        codex_home=codex_home,
    )


@pytest.mark.skipif(
    sys.platform != "linux" or not os.environ.get(_BINARY_ENV),
    reason=f"requires Linux and an explicit absolute {_BINARY_ENV} pin path",
)
async def test_exact_pinned_binary_initializes_in_an_empty_sanitized_cell(
    tmp_path: Path,
) -> None:
    """Opt-in hermetic smoke; it never searches PATH or reads personal Codex state."""

    binary = Path(os.environ[_BINARY_ENV])
    layout = _empty_layout(tmp_path, suffix="smoke")
    supervisor = CodexCellSupervisor(
        binary=binary,
        startup_timeout=10.0,
        initialize_timeout=10.0,
        close_timeout=2.0,
        terminate_timeout=2.0,
        kill_timeout=2.0,
    )

    cell = await supervisor.start(layout, arguments=pinned_arguments(layout))
    try:
        assert cell.metadata.binary_path == binary
        assert cell.metadata.codex_home == layout.codex_home
        assert cell.metadata.platform_family == "unix"
        assert cell.metadata.platform_os == "linux"
    finally:
        await cell.aclose()


@pytest.mark.invariant("SEC-159")
@pytest.mark.skipif(
    sys.platform != "linux" or not os.environ.get(_BINARY_ENV),
    reason=f"requires Linux and an explicit absolute {_BINARY_ENV} pin path",
)
async def test_exact_pinned_binary_accepts_stable_v1_collaboration_limits(
    tmp_path: Path,
) -> None:
    """The exact release accepts the live feature/thread/depth argv contract."""

    binary = Path(os.environ[_BINARY_ENV])
    layout = _empty_layout(tmp_path, suffix="native-v1")
    supervisor = CodexCellSupervisor(
        binary=binary,
        startup_timeout=10.0,
        initialize_timeout=10.0,
        close_timeout=2.0,
        terminate_timeout=2.0,
        kill_timeout=2.0,
    )
    arguments = codex_app_server_arguments(
        cell_id=layout.cell_id,
        helper_path="/opt/boltrig/codex/model_auth_helper",
        socket_name="@boltrig-mp-0123456789abcdef0123456789abcdef",
        proxy_port=41234,
        features=codex_runtime_features(native_agents_enabled=True),
        agent_max_threads=2,
        agent_max_depth=2,
    )

    cell = await supervisor.start(layout, arguments=arguments)
    try:
        assert cell.metadata.binary_path == binary
    finally:
        await cell.aclose()
