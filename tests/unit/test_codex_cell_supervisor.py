from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from boltrig.fleet.infrastructure import codex_cell_supervisor as supervisor_module
from boltrig.fleet.infrastructure import codex_protocol as wire
from boltrig.fleet.infrastructure.codex_cell_policy import (
    CODEX_CLI_SHA256,
    CODEX_CLI_TARGET,
    CODEX_CLI_VERSION,
    CodexUpstreamAuth,
    PinnedCodexBinary,
)
from boltrig.fleet.infrastructure.codex_cell_supervisor import (
    CodexCellStartupError,
    CodexCellSupervisor,
)
from boltrig.fleet.infrastructure.codex_stdio_transport import STDIO_STREAM_LIMIT
from tests.unit.codex_process_fakes import (
    FakeProcess,
    FakeProcessFactory,
    install_initialize_responder,
    make_layout,
)


def fake_binary(tmp_path: Path) -> Path:
    binary = tmp_path / "codex-0.144.3"
    binary.write_bytes(b"test-only binary")
    binary.chmod(0o700)
    return binary


def admit_binary(monkeypatch: pytest.MonkeyPatch, binary: Path) -> None:
    monkeypatch.setattr(
        supervisor_module,
        "verify_pinned_binary",
        lambda path: PinnedCodexBinary(
            path,
            CODEX_CLI_SHA256,
            os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)),
        ),
    )


def inherited_descriptor(factory: FakeProcessFactory) -> int:
    argv = factory.calls[0]["argv"]
    assert isinstance(argv, tuple)
    return int(argv[0].rsplit("/", 1)[1])


async def test_supervisor_spawns_exact_sanitized_stdio_argv_then_returns_initialized_cell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = make_layout(tmp_path)
    binary = fake_binary(tmp_path)
    admit_binary(monkeypatch, binary)
    process = FakeProcess()
    install_initialize_responder(process, codex_home=layout.codex_home)
    factory = FakeProcessFactory(process)
    auth = CodexUpstreamAuth("only-upstream-auth")
    supervisor = CodexCellSupervisor(binary=binary, auth=auth, process_factory=factory)

    cell = await supervisor.start(layout)

    assert cell.client.state is wire.ClientState.READY
    assert cell.metadata.cli_version == CODEX_CLI_VERSION
    assert cell.metadata.cli_target == CODEX_CLI_TARGET
    assert cell.metadata.binary_sha256 == CODEX_CLI_SHA256
    assert cell.metadata.codex_home == layout.codex_home
    assert cell.metadata.workspace_digest == layout.workspace_digest
    call = factory.calls[0]
    argv = call["argv"]
    assert isinstance(argv, tuple)
    assert argv[0].startswith("/proc/self/fd/")
    assert argv[1:] == (
        "app-server",
        "--listen",
        "stdio://",
        "--strict-config",
    )
    descriptor = inherited_descriptor(factory)
    assert call["pass_fds"] == (descriptor,)
    with pytest.raises(OSError):
        os.fstat(descriptor)
    assert call["cwd"] == layout.workspace.as_posix()
    assert call["limit"] == STDIO_STREAM_LIMIT
    assert call["close_fds"] is True
    assert call["stdin"] == call["stdout"] == call["stderr"] == asyncio.subprocess.PIPE
    assert call["env"] == {
        "CODEX_HOME": layout.codex_home.as_posix(),
        "HOME": layout.home.as_posix(),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        "CODEX_ACCESS_TOKEN": "only-upstream-auth",
    }
    methods = [json.loads(frame)["method"] for frame in process.stdin.writes]
    assert methods == ["initialize", "initialized"]
    await cell.aclose()
    assert process.returncode == 0 and cell.closed
    with pytest.raises(CodexCellStartupError, match="previously claimed cell"):
        await supervisor.start(layout)


@pytest.mark.parametrize(
    ("family", "operating_system"),
    [("windows", "linux"), ("unix", "darwin")],
)
async def test_supervisor_rejects_wrong_runtime_platform_and_cleans_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    family: str,
    operating_system: str,
) -> None:
    layout = make_layout(tmp_path)
    binary = fake_binary(tmp_path)
    admit_binary(monkeypatch, binary)
    process = FakeProcess()
    install_initialize_responder(
        process,
        codex_home=layout.codex_home,
        platform_family=family,
        platform_os=operating_system,
    )
    supervisor = CodexCellSupervisor(binary=binary, process_factory=FakeProcessFactory(process))

    with pytest.raises(CodexCellStartupError, match="identity"):
        await supervisor.start(layout)

    assert process.returncode == 0


async def test_supervisor_rejects_wrong_codex_home_and_never_returns_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = make_layout(tmp_path)
    binary = fake_binary(tmp_path)
    admit_binary(monkeypatch, binary)
    process = FakeProcess()
    install_initialize_responder(process, codex_home=layout.home / "wrong")
    supervisor = CodexCellSupervisor(binary=binary, process_factory=FakeProcessFactory(process))

    with pytest.raises(CodexCellStartupError, match="identity"):
        await supervisor.start(layout)

    assert process.returncode == 0


async def test_initialize_timeout_is_bounded_and_kills_owned_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = make_layout(tmp_path)
    binary = fake_binary(tmp_path)
    admit_binary(monkeypatch, binary)
    process = FakeProcess(exit_on_stdin_close=False)
    supervisor = CodexCellSupervisor(
        binary=binary,
        process_factory=FakeProcessFactory(process),
        initialize_timeout=0.01,
        close_timeout=0.01,
        terminate_timeout=0.01,
        kill_timeout=0.01,
    )

    with pytest.raises((wire.RequestTimeoutError, CodexCellStartupError)):
        await supervisor.start(layout)

    assert process.returncode is not None


async def test_cancellation_during_spawn_releases_claim_and_starts_no_orphan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = make_layout(tmp_path)
    binary = fake_binary(tmp_path)
    admit_binary(monkeypatch, binary)
    process = FakeProcess()
    install_initialize_responder(process, codex_home=layout.codex_home)
    factory = FakeProcessFactory(process)
    factory.gate = asyncio.Event()
    supervisor = CodexCellSupervisor(binary=binary, process_factory=factory)
    starting = asyncio.create_task(supervisor.start(layout))
    while not factory.calls:
        await asyncio.sleep(0)

    starting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await starting
    assert factory.allocations == 0
    assert process.returncode is None
    with pytest.raises(OSError):
        os.fstat(inherited_descriptor(factory))

    factory.gate.set()
    retry_layout = make_layout(tmp_path, cell_id="cell-2")
    install_initialize_responder(process, codex_home=retry_layout.codex_home)
    cell = await supervisor.start(retry_layout)
    assert factory.allocations == 1
    await cell.aclose()


async def test_cancellation_reaps_a_factory_process_registered_before_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = make_layout(tmp_path)
    binary = fake_binary(tmp_path)
    admit_binary(monkeypatch, binary)
    process = FakeProcess(exit_on_stdin_close=False)
    factory = FakeProcessFactory(process)
    factory.allocate_before_gate = True
    factory.gate = asyncio.Event()
    supervisor = CodexCellSupervisor(binary=binary, process_factory=factory)
    starting = asyncio.create_task(supervisor.start(layout))
    while factory.allocations == 0:
        await asyncio.sleep(0)

    starting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await starting

    assert process.kill_calls == 1
    assert process.returncode == -9
    with pytest.raises(OSError):
        os.fstat(inherited_descriptor(factory))


async def test_one_active_owner_and_crash_cleanup_allow_replacement_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = make_layout(tmp_path)
    binary = fake_binary(tmp_path)
    admit_binary(monkeypatch, binary)
    process = FakeProcess()
    install_initialize_responder(process, codex_home=layout.codex_home)
    factory = FakeProcessFactory(process)
    supervisor = CodexCellSupervisor(binary=binary, process_factory=factory)
    cell = await supervisor.start(layout)

    with pytest.raises(CodexCellStartupError, match="active Codex owner"):
        await supervisor.start(layout)

    process.feed_stderr(b"secret stderr is discarded")
    process.exit(17)
    await asyncio.wait_for(cell.wait_closed(), 1.0)
    assert cell.returncode == 17

    replacement_layout = make_layout(tmp_path, phase_id=layout.phase_id, cell_id="cell-2")
    replacement = FakeProcess(pid=4322)
    install_initialize_responder(replacement, codex_home=replacement_layout.codex_home)
    factory.process = replacement
    replacement_cell = await supervisor.start(replacement_layout)
    assert replacement_cell.metadata.pid == 4322
    await replacement_cell.aclose()


async def test_client_protocol_failure_automatically_reaps_the_cell_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = make_layout(tmp_path)
    binary = fake_binary(tmp_path)
    admit_binary(monkeypatch, binary)
    process = FakeProcess()
    install_initialize_responder(process, codex_home=layout.codex_home)
    supervisor = CodexCellSupervisor(
        binary=binary, process_factory=FakeProcessFactory(process), close_timeout=0.01
    )
    cell = await supervisor.start(layout)

    process.feed_stdout(b"not-json\n")
    await asyncio.wait_for(cell.wait_closed(), 1.0)

    assert cell.client.state is wire.ClientState.FAILED
    assert process.returncode is not None


async def test_spawn_failure_is_sanitized_and_auth_never_enters_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = make_layout(tmp_path)
    binary = fake_binary(tmp_path)
    admit_binary(monkeypatch, binary)
    factory = FakeProcessFactory(FakeProcess())
    factory.error = RuntimeError("upstream-secret-value")
    supervisor = CodexCellSupervisor(
        binary=binary,
        auth=CodexUpstreamAuth("upstream-secret-value"),
        process_factory=factory,
    )

    with pytest.raises(CodexCellStartupError) as captured:
        await supervisor.start(layout)

    assert "upstream-secret-value" not in str(captured.value)
    assert "upstream-secret-value" not in repr(captured.value)
    with pytest.raises(OSError):
        os.fstat(inherited_descriptor(factory))


async def test_cancelling_cell_close_still_finishes_process_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = make_layout(tmp_path)
    binary = fake_binary(tmp_path)
    admit_binary(monkeypatch, binary)
    process = FakeProcess(exit_on_stdin_close=False)
    install_initialize_responder(process, codex_home=layout.codex_home)
    supervisor = CodexCellSupervisor(
        binary=binary,
        process_factory=FakeProcessFactory(process),
        close_timeout=0.1,
    )
    cell = await supervisor.start(layout)
    closing = asyncio.create_task(cell.aclose())
    await asyncio.sleep(0)

    closing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await closing

    assert process.returncode is not None
    assert cell.closed


async def test_on_spawned_runs_with_the_real_pid_before_any_protocol_traffic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Registration must precede the first byte, so no live cell is unregistered."""

    layout = make_layout(tmp_path)
    binary = fake_binary(tmp_path)
    admit_binary(monkeypatch, binary)
    process = FakeProcess()
    install_initialize_responder(process, codex_home=layout.codex_home)
    factory = FakeProcessFactory(process)
    supervisor = CodexCellSupervisor(binary=binary, process_factory=factory)
    seen: dict[str, object] = {}

    async def on_spawned(pid: int) -> None:
        seen["pid"] = pid
        seen["writes"] = list(process.stdin.writes)

    cell = await supervisor.start(layout, on_spawned=on_spawned)

    assert seen["pid"] == process.pid == cell.metadata.pid
    assert seen["writes"] == []  # nothing had been sent yet
    await cell.aclose()


async def test_on_spawned_failure_reaps_the_process_and_releases_the_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cell that cannot be registered is never handed out."""

    layout = make_layout(tmp_path)
    binary = fake_binary(tmp_path)
    admit_binary(monkeypatch, binary)
    process = FakeProcess()
    install_initialize_responder(process, codex_home=layout.codex_home)
    supervisor = CodexCellSupervisor(
        binary=binary, process_factory=FakeProcessFactory(process)
    )

    async def on_spawned(pid: int) -> None:
        raise RuntimeError("registration refused")

    with pytest.raises(CodexCellStartupError):
        await supervisor.start(layout, on_spawned=on_spawned)

    assert process.returncode is not None  # reaped, no orphan


async def test_on_spawned_hang_is_bounded_and_reaps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A registry that never answers must not hang the spawn forever."""

    layout = make_layout(tmp_path)
    binary = fake_binary(tmp_path)
    admit_binary(monkeypatch, binary)
    process = FakeProcess()
    install_initialize_responder(process, codex_home=layout.codex_home)
    supervisor = CodexCellSupervisor(
        binary=binary,
        process_factory=FakeProcessFactory(process),
        startup_timeout=0.05,
    )

    async def on_spawned(pid: int) -> None:
        await asyncio.sleep(3600)

    with pytest.raises(CodexCellStartupError):
        await supervisor.start(layout, on_spawned=on_spawned)

    assert process.returncode is not None
