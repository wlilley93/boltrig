"""Disabled-by-default local supervisor for initialized read-only Codex cells."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from . import codex_protocol as wire
from .codex_app_server import CodexAppServerClient
from .cell_lane import CellLane
from .codex_runtime_config_argv import validate_app_server_arguments
from .codex_cell_policy import (
    CODEX_CLI_SHA256,
    CODEX_CLI_TARGET,
    CODEX_CLI_VERSION,
    CodexCellLayout,
    CodexCellPolicyError,
    CodexUpstreamAuth,
    PinnedCodexBinary,
    attest_workspace_projection,
    normalized_absolute_path,
    sanitized_environment,
    validate_cell_layout,
    verify_pinned_binary,
)
from .codex_stdio_transport import (
    validated_timeout,
    CodexStdioTransport,
    ManagedCodexProcess,
)
from .codex_process_spawn import (
    CodexProcessFactory,
    CodexProcessSpawnError,
    default_process_factory,
    spawn_registered_process,
)


class CodexCellStartupError(wire.CodexAppServerError):
    """A local Codex cell could not reach its verified initialized state."""


ReleaseCell = Callable[[str, str], Awaitable[None]]
# Run against the just-spawned child pid, before any protocol traffic. If it does
# not succeed the cell is never handed out. The supervisor treats it as opaque.
OnCellSpawned = Callable[[int], Awaitable[None]]


def _close_late_binary(task: asyncio.Task[PinnedCodexBinary]) -> None:
    """Close a descriptor returned after its bounded caller stopped waiting."""

    if task.cancelled():
        return
    try:
        task.result().close()
    except Exception:
        pass


@dataclass(frozen=True)
class CodexCellMetadata:
    phase_id: str
    cell_id: str
    pid: int
    cli_version: str
    cli_target: str
    binary_sha256: str
    binary_path: Path
    workspace: Path
    workspace_digest: str
    home: Path
    codex_home: Path
    platform_family: str
    platform_os: str
    user_agent: str


@dataclass(repr=False)
class InitializedCodexCell:
    """Single-owner lease for one initialized process and client."""

    client: CodexAppServerClient = field(repr=False)
    metadata: CodexCellMetadata
    _transport: CodexStdioTransport = field(repr=False)
    _release: ReleaseCell = field(repr=False)
    _monitor: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _close_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _closed_event: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)
    _released: bool = field(default=False, init=False, repr=False)
    _cleanup_failed: bool = field(default=False, init=False, repr=False)

    @property
    def returncode(self) -> int | None:
        return self._transport.returncode

    @property
    def cleanup_failed(self) -> bool:
        return self._cleanup_failed

    @property
    def closed(self) -> bool:
        return self._closed_event.is_set()

    def start_monitor(self) -> None:
        if self._monitor is not None:
            raise RuntimeError("Codex cell monitor cannot be reused")
        self._monitor = asyncio.create_task(
            self._monitor_process(), name=f"codex-cell-monitor-{self.metadata.cell_id}"
        )

    async def wait_closed(self) -> None:
        await self._closed_event.wait()

    async def aclose(self) -> None:
        async with self._close_lock:
            if self._closed_event.is_set():
                return
            task = asyncio.create_task(
                self._close_owned(), name=f"codex-cell-close-{self.metadata.cell_id}"
            )
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise

    async def __aenter__(self) -> InitializedCodexCell:
        if self.closed:
            raise RuntimeError("Codex cell lease cannot be reused")
        return self

    async def __aexit__(self, _type: object, _value: object, _traceback: object) -> None:
        await self.aclose()

    async def _monitor_process(self) -> None:
        exit_task = asyncio.create_task(self._transport.wait())
        try:
            while not exit_task.done():
                await asyncio.wait({exit_task}, timeout=0.05)
                if self.client.state in {wire.ClientState.FAILED, wire.ClientState.CLOSED}:
                    break
            try:
                await self._transport.aclose()
            except Exception:
                self._cleanup_failed = True
        finally:
            if not exit_task.done():
                exit_task.cancel()
            await asyncio.gather(exit_task, return_exceptions=True)
            await self._release_once()
            self._closed_event.set()

    async def _close_owned(self) -> None:
        try:
            await self.client.aclose()
        except Exception:
            self._cleanup_failed = True
            try:
                await self._transport.aclose()
            except Exception:
                pass
        monitor = self._monitor
        if monitor is not None and monitor is not asyncio.current_task():
            await asyncio.gather(monitor, return_exceptions=True)
        await self._release_once()
        self._closed_event.set()

    async def _release_once(self) -> None:
        if not self._released:
            self._released = True
            await self._release(self.metadata.phase_id, self.metadata.cell_id)


class CodexCellSupervisor:
    """Spawn one stdio App Server for each admitted active phase."""

    def __init__(
        self,
        *,
        binary: Path,
        auth: CodexUpstreamAuth | None = None,
        process_factory: CodexProcessFactory | None = None,
        startup_timeout: float = 10.0,
        initialize_timeout: float = 15.0,
        write_timeout: float = 10.0,
        close_timeout: float = 3.0,
        terminate_timeout: float = 3.0,
        kill_timeout: float = 3.0,
        cell_lane: CellLane | None = None,
    ) -> None:
        self._binary_path = normalized_absolute_path("Codex binary", binary)
        # J1: None means today's in-process spawn. See cell_lane for why the lane
        # re-checks the kernel rather than trusting that it was constructed.
        if cell_lane is not None and type(cell_lane) is not CellLane:
            raise TypeError("cell_lane must be an exact CellLane or None")
        self._cell_lane = cell_lane
        if auth is not None and type(auth) is not CodexUpstreamAuth:
            raise TypeError("auth must be CodexUpstreamAuth or None")
        self._auth = auth
        self._factory = process_factory or default_process_factory
        self._startup_timeout = validated_timeout("startup timeout", startup_timeout)
        self._initialize_timeout = validated_timeout("initialize timeout", initialize_timeout)
        self._transport_timeouts = tuple(
            validated_timeout(label, value)
            for label, value in (
                ("write timeout", write_timeout),
                ("close timeout", close_timeout),
                ("terminate timeout", terminate_timeout),
                ("kill timeout", kill_timeout),
            )
        )
        self._claim_lock = asyncio.Lock()
        self._active_phases: set[str] = set()
        self._claimed_cells: set[str] = set()

    async def start(
        self,
        layout: CodexCellLayout,
        *,
        arguments: tuple[str, ...],
        on_spawned: OnCellSpawned | None = None,
    ) -> InitializedCodexCell:
        admitted = validate_cell_layout(layout)
        # [2026] VJS-CC-VJS 6 H5: argv is REQUIRED, never defaulted. A caller who
        # forgets to pin gets a TypeError at the call site rather than a silently
        # unpinned App Server, and an argv minted for another cell is refused here
        # rather than discovered when the helper fetches the wrong bearer.
        pinned = validate_app_server_arguments(arguments, cell_id=admitted.cell_id)
        await self._attest_workspace(admitted)
        await self._claim(admitted.phase_id, admitted.cell_id)
        process: ManagedCodexProcess | None = None
        transport: CodexStdioTransport | None = None
        client: CodexAppServerClient | None = None
        try:
            if self._binary_path.is_relative_to(admitted.cell_root):
                raise CodexCellPolicyError("Codex binary must be outside the mutable cell root")
            binary = await self._verify_binary()
            process = await self._spawn(binary, admitted, pinned)
            if on_spawned is not None:
                # Earliest instant the pid exists; every failure below reaps it.
                await asyncio.wait_for(on_spawned(process.pid), self._startup_timeout)
            transport = self._make_transport(process)
            client = CodexAppServerClient(
                transport,
                client_version=CODEX_CLI_VERSION,
                request_timeout=self._initialize_timeout,
            )
            receipt = await asyncio.wait_for(client.initialize(), self._initialize_timeout)
            metadata = self._metadata(receipt, process, binary, admitted)
            cell = InitializedCodexCell(client, metadata, transport, self._release)
            cell.start_monitor()
            return cell
        except asyncio.CancelledError:
            await self._cleanup_failed_start(client, transport, process, admitted)
            raise
        except (CodexCellPolicyError, wire.CodexAppServerError):
            await self._cleanup_failed_start(client, transport, process, admitted)
            raise
        except TimeoutError:
            await self._cleanup_failed_start(client, transport, process, admitted)
            raise CodexCellStartupError("Codex cell startup timed out") from None
        except Exception:
            await self._cleanup_failed_start(client, transport, process, admitted)
            raise CodexCellStartupError("Codex cell startup failed") from None

    async def _verify_binary(self) -> PinnedCodexBinary:
        task = asyncio.create_task(asyncio.to_thread(verify_pinned_binary, self._binary_path))
        try:
            return await asyncio.wait_for(
                asyncio.shield(task),
                self._startup_timeout,
            )
        except TimeoutError:
            task.add_done_callback(_close_late_binary)
            raise CodexCellStartupError("Codex binary verification timed out") from None
        except asyncio.CancelledError:
            task.add_done_callback(_close_late_binary)
            raise

    async def _attest_workspace(self, layout: CodexCellLayout) -> None:
        try:
            await asyncio.wait_for(
                asyncio.to_thread(attest_workspace_projection, layout.workspace_projection),
                self._startup_timeout,
            )
        except TimeoutError:
            raise CodexCellStartupError("Codex workspace re-attestation timed out") from None

    async def _spawn(
        self,
        binary: PinnedCodexBinary,
        layout: CodexCellLayout,
        arguments: tuple[str, ...],
    ) -> ManagedCodexProcess:
        environment = sanitized_environment(layout, self._auth)
        try:
            if self._cell_lane is not None:  # J1: per-cell uid, via the spawner
                return await self._cell_lane.spawn(
                    binary=binary, arguments=arguments,
                    cwd=layout.workspace.as_posix(), environment=environment,
                )
            return await spawn_registered_process(
                self._factory,
                binary=binary.execution_path,
                arguments=arguments,
                cwd=layout.workspace.as_posix(),
                environment=environment,
                pass_fds=(binary.fileno(),),
                timeout=self._startup_timeout,
                cleanup_timeout=self._transport_timeouts[-1],
            )
        except CodexProcessSpawnError:
            raise CodexCellStartupError("Codex process spawn failed") from None
        finally:
            binary.close()

    def _make_transport(self, process: ManagedCodexProcess) -> CodexStdioTransport:
        write, close, terminate, kill = self._transport_timeouts
        return CodexStdioTransport(
            process,
            write_timeout=write,
            close_timeout=close,
            terminate_timeout=terminate,
            kill_timeout=kill,
        )

    def _metadata(
        self,
        receipt: wire.CallReceipt,
        process: ManagedCodexProcess,
        binary: PinnedCodexBinary,
        layout: CodexCellLayout,
    ) -> CodexCellMetadata:
        payload = receipt.payload.to_mapping()
        if (
            payload.get("codexHome") != layout.codex_home.as_posix()
            or payload.get("platformFamily") != "unix"
            or payload.get("platformOs") != "linux"
            or type(payload.get("userAgent")) is not str
            or not cast(str, payload["userAgent"]).strip()
        ):
            raise CodexCellStartupError("Codex initialize identity did not match the cell")
        return CodexCellMetadata(
            phase_id=layout.phase_id,
            cell_id=layout.cell_id,
            pid=process.pid,
            cli_version=CODEX_CLI_VERSION,
            cli_target=CODEX_CLI_TARGET,
            binary_sha256=CODEX_CLI_SHA256,
            binary_path=binary.path,
            workspace=layout.workspace,
            workspace_digest=layout.workspace_digest,
            home=layout.home,
            codex_home=layout.codex_home,
            platform_family="unix",
            platform_os="linux",
            user_agent=cast(str, payload["userAgent"]),
        )

    async def _claim(self, phase_id: str, cell_id: str) -> None:
        async with self._claim_lock:
            if phase_id in self._active_phases or cell_id in self._claimed_cells:
                raise CodexCellStartupError("active Codex owner or previously claimed cell")
            self._active_phases.add(phase_id)
            self._claimed_cells.add(cell_id)

    async def _release(self, phase_id: str, cell_id: str) -> None:
        async with self._claim_lock:
            self._active_phases.discard(phase_id)

    async def _cleanup_failed_start(
        self,
        client: CodexAppServerClient | None,
        transport: CodexStdioTransport | None,
        process: ManagedCodexProcess | None,
        layout: CodexCellLayout,
    ) -> None:
        async def cleanup() -> None:
            try:
                if client is not None:
                    await client.aclose()
                elif transport is not None:
                    await transport.aclose()
                elif process is not None and process.returncode is None:
                    process.kill()
                    await asyncio.wait_for(process.wait(), self._transport_timeouts[-1])
            except Exception:
                pass
            finally:
                await self._release(layout.phase_id, layout.cell_id)

        task = asyncio.create_task(cleanup(), name=f"codex-start-cleanup-{layout.cell_id}")
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
