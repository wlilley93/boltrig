from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from boltrig.fleet.infrastructure import codex_cell_policy as policy
from boltrig.fleet.infrastructure import codex_cell_supervisor as supervisor_module
from boltrig.fleet.infrastructure import bounded_filesystem
from boltrig.fleet.infrastructure.bounded_filesystem import DirectoryCapture, FilesystemLimits
from boltrig.fleet.infrastructure.codex_cell_policy import (
    CODEX_CLI_SHA256,
    CodexCellLayout,
    PinnedCodexBinary,
)
from boltrig.fleet.infrastructure.codex_cell_supervisor import CodexCellSupervisor
from boltrig.fleet.infrastructure.skill_artifacts import project_sanitized_workspace
from tests.unit.codex_process_fakes import (

    pinned_arguments,
    FakeProcess,
    FakeProcessFactory,
    install_initialize_responder,
)

# Every leg here needs a Linux kernel facility macOS does not have: yama
# ptrace_scope, abstract AF_UNIX names, SO_PEERCRED, or bubblewrap. Marked so a
# non-Linux box reports them as unverified instead of failing; on Linux the
# marker is inert and they always run.
pytestmark = pytest.mark.linux_only


@pytest.fixture(autouse=True)
def _restore_test_tree_permissions(tmp_path: Path) -> Iterator[None]:
    """Leave immutable projections removable even when an assertion fails."""

    yield
    for root, _directories, files in os.walk(tmp_path, topdown=True, followlinks=False):
        root_path = Path(root)
        root_path.chmod(0o700, follow_symlinks=False)
        for name in files:
            path = root_path / name
            if not path.is_symlink():
                path.chmod(0o600, follow_symlinks=False)


def _directory(path: Path) -> Path:
    path.mkdir()
    path.chmod(0o700)
    return path


def _projected_layout(tmp_path: Path) -> CodexCellLayout:
    source = _directory(tmp_path / "source")
    (source / "README.md").write_text("reviewed workspace\n", encoding="utf-8")
    controls = _directory(source / ".git")
    (controls / "config").write_text("must not project", encoding="utf-8")
    stack = _directory(tmp_path / "stack")
    cell = _directory(stack / "cell-1")
    projection = project_sanitized_workspace(
        source,
        cell_root=cell,
        destination=cell / "workspace",
    )
    return CodexCellLayout(
        phase_id="phase-1",
        cell_id="cell-1",
        stack_root=stack,
        cell_root=cell,
        workspace_projection=projection,
        home=_directory(cell / "home"),
        codex_home=_directory(cell / "codex-home"),
    )


def _binary(tmp_path: Path) -> Path:
    binary = tmp_path / "codex-0.144.3"
    binary.write_bytes(b"reviewed executable")
    binary.chmod(0o700)
    return binary


def _admit_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    def verify(path: Path) -> PinnedCodexBinary:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
        return PinnedCodexBinary(path, CODEX_CLI_SHA256, descriptor)

    monkeypatch.setattr(supervisor_module, "verify_pinned_binary", verify)


def _ready_supervisor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    layout: CodexCellLayout,
) -> tuple[CodexCellSupervisor, FakeProcessFactory]:
    binary = _binary(tmp_path)
    _admit_binary(monkeypatch)
    process = FakeProcess()
    install_initialize_responder(process, codex_home=layout.codex_home)
    factory = FakeProcessFactory(process)
    return CodexCellSupervisor(binary=binary, process_factory=factory), factory


async def test_supervisor_reattests_a_real_sanitized_projection_before_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _projected_layout(tmp_path)
    supervisor, factory = _ready_supervisor(tmp_path, monkeypatch, layout)

    cell = await supervisor.start(layout, arguments=pinned_arguments(layout))

    assert factory.calls
    assert (layout.workspace / "README.md").read_text(encoding="utf-8") == (
        "reviewed workspace\n"
    )
    assert not (layout.workspace / ".git").exists()
    await cell.aclose()


async def test_forged_projection_accounting_fails_before_claim_or_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _projected_layout(tmp_path)
    forged = replace(
        layout,
        workspace_projection=replace(
            layout.workspace_projection,
            workspace_digest="sha256:" + "0" * 64,
            file_count=layout.workspace_projection.file_count + 1,
            total_bytes=layout.workspace_projection.total_bytes + 1,
        ),
    )
    supervisor, factory = _ready_supervisor(tmp_path, monkeypatch, layout)

    with pytest.raises(policy.CodexCellPolicyError, match="does not match"):
        await supervisor.start(forged, arguments=pinned_arguments(layout))

    assert factory.calls == []
    cell = await supervisor.start(layout, arguments=pinned_arguments(layout))
    await cell.aclose()


async def test_workspace_byte_tamper_fails_before_process_allocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _projected_layout(tmp_path)
    readme = layout.workspace / "README.md"
    layout.workspace.chmod(0o700)
    readme.chmod(0o600)
    readme.write_text("tampered workspace\n", encoding="utf-8")
    readme.chmod(0o400)
    layout.workspace.chmod(0o500)
    supervisor, factory = _ready_supervisor(tmp_path, monkeypatch, layout)

    with pytest.raises(policy.CodexCellPolicyError, match="does not match"):
        await supervisor.start(layout, arguments=pinned_arguments(layout))

    assert factory.calls == []


async def test_workspace_file_mode_tamper_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _projected_layout(tmp_path)
    (layout.workspace / "README.md").chmod(0o440)
    supervisor, factory = _ready_supervisor(tmp_path, monkeypatch, layout)

    with pytest.raises(policy.CodexCellPolicyError, match="unsafe mode"):
        await supervisor.start(layout, arguments=pinned_arguments(layout))

    assert factory.calls == []


@pytest.mark.parametrize("injection", ["symlink", "control"])
async def test_workspace_unsafe_injection_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    injection: str,
) -> None:
    layout = _projected_layout(tmp_path)
    layout.workspace.chmod(0o700)
    if injection == "symlink":
        readme = layout.workspace / "README.md"
        readme.unlink()
        readme.symlink_to(layout.workspace_projection.source_path + "/README.md")
    else:
        control = _directory(layout.workspace / ".agents")
        (control / "SKILL.md").write_text("injected", encoding="utf-8")
    layout.workspace.chmod(0o500)
    supervisor, factory = _ready_supervisor(tmp_path, monkeypatch, layout)

    with pytest.raises(policy.CodexCellPolicyError, match="re-attestation failed"):
        await supervisor.start(layout, arguments=pinned_arguments(layout))

    assert factory.calls == []
    layout.workspace.chmod(0o700)
    if injection == "symlink":
        (layout.workspace / "README.md").unlink()
    else:
        control = layout.workspace / ".agents"
        (control / "SKILL.md").unlink()
        control.rmdir()


async def test_workspace_change_between_bounded_captures_fails_as_a_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _projected_layout(tmp_path)
    real_capture = bounded_filesystem.capture_directory
    capture_calls = 0

    def racing_capture(
        root: Path,
        limits: FilesystemLimits,
        *,
        reject_controls: bool,
    ) -> DirectoryCapture:
        nonlocal capture_calls
        capture = real_capture(root, limits, reject_controls=reject_controls)
        capture_calls += 1
        if capture_calls == 1:
            readme = layout.workspace / "README.md"
            layout.workspace.chmod(0o700)
            readme.chmod(0o600)
            readme.write_text("raced workspace\n", encoding="utf-8")
            readme.chmod(0o400)
            layout.workspace.chmod(0o500)
        return capture

    monkeypatch.setattr(policy, "capture_directory", racing_capture)
    supervisor, factory = _ready_supervisor(tmp_path, monkeypatch, layout)

    with pytest.raises(policy.CodexCellPolicyError, match="changed"):
        await supervisor.start(layout, arguments=pinned_arguments(layout))

    assert factory.calls == []


@pytest.mark.skipif(not Path("/proc/self/fd").is_dir(), reason="Linux executable fd seam")
async def test_supervisor_exec_target_survives_verified_path_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _projected_layout(tmp_path)
    supervisor, factory = _ready_supervisor(tmp_path, monkeypatch, layout)
    binary = tmp_path / "codex-0.144.3"
    observed: list[bytes] = []

    def replace_path(call: dict[str, object]) -> None:
        binary.rename(tmp_path / "verified-inode")
        binary.write_bytes(b"unreviewed replacement")
        binary.chmod(0o700)
        argv = call["argv"]
        assert isinstance(argv, tuple)
        observed.append(Path(argv[0]).read_bytes())

    factory.before_allocate = replace_path

    cell = await supervisor.start(layout, arguments=pinned_arguments(layout))

    assert observed == [b"reviewed executable"]
    assert cell.metadata.binary_path == binary
    await cell.aclose()


async def test_cancellation_during_binary_verification_closes_late_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = _projected_layout(tmp_path)
    binary = _binary(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    descriptors: list[int] = []

    def delayed_verify(path: Path) -> PinnedCodexBinary:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
        descriptors.append(descriptor)
        entered.set()
        release.wait(1.0)
        return PinnedCodexBinary(path, CODEX_CLI_SHA256, descriptor)

    monkeypatch.setattr(supervisor_module, "verify_pinned_binary", delayed_verify)
    supervisor = CodexCellSupervisor(
        binary=binary,
        process_factory=FakeProcessFactory(FakeProcess()),
    )
    starting = asyncio.create_task(supervisor.start(layout, arguments=pinned_arguments(layout)))
    while not entered.is_set():
        await asyncio.sleep(0)

    starting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await starting
    release.set()
    for _attempt in range(100):
        try:
            os.fstat(descriptors[0])
        except OSError:
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("late verified Codex descriptor was not closed")
