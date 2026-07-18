"""Cancellation-safe subprocess allocation for the pinned local Codex cell."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Protocol, cast

from . import codex_protocol as wire
from .codex_stdio_transport import STDIO_STREAM_LIMIT, ManagedCodexProcess

ProcessAllocated = Callable[[ManagedCodexProcess], None]


class CodexProcessSpawnError(wire.CodexAppServerError):
    """A process factory failed without leaking arguments or environment."""


class CodexProcessFactory(Protocol):
    """Factory that registers a child before awaiting after its allocation."""

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
    ) -> ManagedCodexProcess: ...


async def default_process_factory(
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
    # The pin is Linux-only. asyncio's Unix subprocess implementation closes
    # and waits for a child if creation is cancelled before it can return.
    process = cast(
        ManagedCodexProcess,
        await asyncio.create_subprocess_exec(
            binary,
            *arguments,
            cwd=cwd,
            env=env,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            limit=limit,
            close_fds=close_fds,
            pass_fds=pass_fds,
        ),
    )
    allocated(process)
    return process


async def _kill_and_reap(processes: tuple[ManagedCodexProcess, ...], timeout: float) -> None:
    for process in processes:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
    for process in processes:
        if process.returncode is None:
            try:
                await asyncio.wait_for(asyncio.shield(process.wait()), timeout)
            except Exception:
                pass


async def _shielded_cleanup(processes: tuple[ManagedCodexProcess, ...], timeout: float) -> None:
    task = asyncio.create_task(_kill_and_reap(processes, timeout))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await task


async def spawn_registered_process(
    factory: CodexProcessFactory,
    *,
    binary: str,
    arguments: tuple[str, ...],
    cwd: str,
    environment: dict[str, str],
    pass_fds: tuple[int, ...],
    timeout: float,
    cleanup_timeout: float,
) -> ManagedCodexProcess:
    if (
        type(pass_fds) is not tuple
        or len(pass_fds) != 1
        or type(pass_fds[0]) is not int
        or pass_fds[0] < 0
    ):
        raise CodexProcessSpawnError("Codex process requires one pinned executable descriptor")
    registered: list[ManagedCodexProcess] = []

    def allocated(process: ManagedCodexProcess) -> None:
        registered.append(process)
        if len(registered) > 1:
            raise CodexProcessSpawnError("Codex factory registered more than one process")

    try:
        process = await asyncio.wait_for(
            factory(
                binary,
                *arguments,
                cwd=cwd,
                env=environment,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=STDIO_STREAM_LIMIT,
                close_fds=True,
                pass_fds=pass_fds,
                allocated=allocated,
            ),
            timeout,
        )
    except asyncio.CancelledError:
        await _shielded_cleanup(tuple(registered), cleanup_timeout)
        raise
    except TimeoutError:
        await _shielded_cleanup(tuple(registered), cleanup_timeout)
        raise CodexProcessSpawnError("Codex process spawn timed out") from None
    except Exception:
        await _shielded_cleanup(tuple(registered), cleanup_timeout)
        raise CodexProcessSpawnError("Codex process spawn failed") from None
    if not registered:
        await _shielded_cleanup((process,), cleanup_timeout)
        raise CodexProcessSpawnError("Codex factory returned an unregistered process")
    if registered[0] is not process:
        await _shielded_cleanup((*registered, process), cleanup_timeout)
        raise CodexProcessSpawnError("Codex factory returned an unregistered process")
    if process.returncode is not None:
        raise CodexProcessSpawnError("Codex process exited before initialization")
    return process
