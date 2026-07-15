from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

from boltrig.fleet.infrastructure.codex_cell_policy import CodexCellLayout
from boltrig.fleet.infrastructure.codex_process_spawn import ProcessAllocated
from boltrig.fleet.infrastructure.skill_artifacts import (
    SanitizedWorkspaceProjection,
    digest_directory,
)
from boltrig.fleet.infrastructure.codex_stdio_transport import (
    STDIO_STREAM_LIMIT,
    ManagedCodexProcess,
)


class FakeStdin:
    def __init__(self, process: FakeProcess) -> None:
        self._process = process
        self.writes: list[bytes] = []
        self.closed = False
        self.drain_gate: asyncio.Event | None = None
        self.drain_error: Exception | None = None

    def write(self, data: bytes) -> None:
        if self.closed:
            raise BrokenPipeError
        self.writes.append(data)
        self._process.on_stdin(data)

    async def drain(self) -> None:
        if self.drain_gate is not None:
            await self.drain_gate.wait()
        if self.drain_error is not None:
            raise self.drain_error

    def close(self) -> None:
        self.closed = True
        if self._process.exit_on_stdin_close:
            self._process.exit(0)

    async def wait_closed(self) -> None:
        return


class FakeProcess:
    def __init__(
        self,
        *,
        pid: int = 4321,
        exit_on_stdin_close: bool = True,
        exit_on_terminate: bool = True,
        exit_on_kill: bool = True,
    ) -> None:
        self.pid = pid
        self.stdout = asyncio.StreamReader(limit=STDIO_STREAM_LIMIT)
        self.stderr = asyncio.StreamReader(limit=64 * 1024)
        self.stdin = FakeStdin(self)
        self.exit_on_stdin_close = exit_on_stdin_close
        self.exit_on_terminate = exit_on_terminate
        self.exit_on_kill = exit_on_kill
        self.terminate_calls = 0
        self.kill_calls = 0
        self._returncode: int | None = None
        self._exited = asyncio.Event()
        self.stdin_callback: Callable[[bytes], None] | None = None

    @property
    def returncode(self) -> int | None:
        return self._returncode

    def on_stdin(self, data: bytes) -> None:
        if self.stdin_callback is not None:
            self.stdin_callback(data)

    def feed_stdout(self, line: bytes) -> None:
        self.stdout.feed_data(line)

    def feed_stderr(self, value: bytes) -> None:
        self.stderr.feed_data(value)

    def exit(self, returncode: int) -> None:
        if self._returncode is not None:
            return
        self._returncode = returncode
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self._exited.set()

    async def wait(self) -> int:
        await self._exited.wait()
        assert self._returncode is not None
        return self._returncode

    def terminate(self) -> None:
        self.terminate_calls += 1
        if self.exit_on_terminate:
            self.exit(-15)

    def kill(self) -> None:
        self.kill_calls += 1
        if self.exit_on_kill:
            self.exit(-9)


class FakeProcessFactory:
    def __init__(self, process: FakeProcess) -> None:
        self.process = process
        self.calls: list[dict[str, object]] = []
        self.allocations = 0
        self.gate: asyncio.Event | None = None
        self.error: Exception | None = None
        self.allocate_before_gate = False
        self.before_allocate: Callable[[dict[str, object]], None] | None = None

    async def __call__(
        self,
        binary: str,
        *arguments: str,
        cwd: str,
        env: dict[str, str],
        stdin: int,
        stdout: int,
        stderr: int,
        limit: int,
        close_fds: bool,
        pass_fds: tuple[int, ...],
        allocated: ProcessAllocated,
    ) -> ManagedCodexProcess:
        call = {
            "argv": (binary, *arguments),
            "cwd": cwd,
            "env": dict(env),
            "stdin": stdin,
            "stdout": stdout,
            "stderr": stderr,
            "limit": limit,
            "close_fds": close_fds,
            "pass_fds": pass_fds,
        }
        self.calls.append(call)
        if self.before_allocate is not None:
            self.before_allocate(call)
        if self.allocate_before_gate:
            allocated(cast(ManagedCodexProcess, self.process))
            self.allocations += 1
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        if not self.allocate_before_gate:
            allocated(cast(ManagedCodexProcess, self.process))
            self.allocations += 1
        return cast(ManagedCodexProcess, self.process)


def make_layout(
    tmp_path: Path, *, phase_id: str = "phase-1", cell_id: str = "cell-1"
) -> CodexCellLayout:
    stack = tmp_path / "stack"
    cell = stack / cell_id
    workspace = cell / "workspace"
    home = cell / "home"
    codex_home = cell / "codex-home"
    for directory in (stack, cell, workspace, home, codex_home):
        directory.mkdir(exist_ok=True)
        directory.chmod(0o700)
    workspace.chmod(0o500)
    accounting = digest_directory(workspace)
    return CodexCellLayout(
        phase_id=phase_id,
        cell_id=cell_id,
        stack_root=stack,
        cell_root=cell,
        workspace_projection=SanitizedWorkspaceProjection(
            source_path=(tmp_path / "source").as_posix(),
            workspace_path=workspace.as_posix(),
            workspace_digest=accounting.digest,
            file_count=accounting.file_count,
            total_bytes=accounting.total_bytes,
        ),
        home=home,
        codex_home=codex_home,
    )


def install_initialize_responder(
    process: FakeProcess,
    *,
    codex_home: Path,
    platform_family: str = "unix",
    platform_os: str = "linux",
) -> None:
    def respond(data: bytes) -> None:
        message = json.loads(data)
        if message.get("method") != "initialize":
            return
        response = {
            "id": message["id"],
            "result": {
                "codexHome": codex_home.as_posix(),
                "platformFamily": platform_family,
                "platformOs": platform_os,
                "userAgent": "boltrig/0.1.0 codex/0.144.3",
            },
        }
        process.feed_stdout(json.dumps(response, separators=(",", ":")).encode() + b"\n")

    process.stdin_callback = respond
