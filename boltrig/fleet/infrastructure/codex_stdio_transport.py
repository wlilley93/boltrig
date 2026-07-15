"""Allocation-bounded stdio transport for one local Codex App Server process."""

from __future__ import annotations

import asyncio
import contextlib
import math
from typing import Protocol, cast

from . import codex_protocol as wire

STDIO_STREAM_LIMIT = wire.MAX_LINE_BYTES
STDERR_CHUNK_BYTES = 16 * 1024


class CodexProcessExitedError(wire.CodexTransportError):
    """The owned App Server process exited or closed stdout."""

    def __init__(self, returncode: int | None) -> None:
        self.returncode = returncode
        suffix = "" if returncode is None else f" with status {returncode}"
        super().__init__(f"Codex App Server process exited{suffix}")


class CodexStdin(Protocol):
    def write(self, data: bytes) -> None: ...

    async def drain(self) -> None: ...

    def close(self) -> None: ...

    async def wait_closed(self) -> None: ...


class ManagedCodexProcess(Protocol):
    """Small subprocess surface used by the transport and deterministic fakes."""

    pid: int
    stdin: CodexStdin | None
    stdout: asyncio.StreamReader | None
    stderr: asyncio.StreamReader | None

    @property
    def returncode(self) -> int | None: ...

    async def wait(self) -> int: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


def _timeout(label: str, value: object) -> float:
    if type(value) not in {int, float}:
        raise TypeError(f"{label} must be a finite positive number")
    numeric = float(cast(int | float, value))
    if not math.isfinite(numeric) or numeric <= 0:
        raise ValueError(f"{label} must be a finite positive number")
    return numeric


class CodexStdioTransport:
    """Own one process and expose its stdio as strict JSONL frames."""

    def __init__(
        self,
        process: ManagedCodexProcess,
        *,
        write_timeout: float,
        close_timeout: float,
        terminate_timeout: float,
        kill_timeout: float,
        max_frame_bytes: int = wire.MAX_LINE_BYTES,
    ) -> None:
        if type(process.pid) is not int or process.pid <= 0:
            raise TypeError("Codex process must expose a positive integer pid")
        if process.stdin is None or process.stdout is None or process.stderr is None:
            raise TypeError("Codex process must expose piped stdin, stdout, and stderr")
        if type(max_frame_bytes) is not int or max_frame_bytes != STDIO_STREAM_LIMIT:
            raise ValueError("max_frame_bytes must match the fixed subprocess stream limit")
        self._process = process
        self._stdin = process.stdin
        self._stdout = process.stdout
        self._stderr = process.stderr
        self._write_timeout = _timeout("write timeout", write_timeout)
        self._close_timeout = _timeout("close timeout", close_timeout)
        self._terminate_timeout = _timeout("terminate timeout", terminate_timeout)
        self._kill_timeout = _timeout("kill timeout", kill_timeout)
        self._max_frame_bytes = max_frame_bytes
        self._read_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()
        self._closed = False
        self._stderr_task = asyncio.create_task(
            self._discard_stderr(), name=f"codex-stderr-drain-{process.pid}"
        )

    @property
    def pid(self) -> int:
        return self._process.pid

    @property
    def returncode(self) -> int | None:
        return self._process.returncode

    @property
    def closed(self) -> bool:
        return self._closed

    async def write_line(self, line: str) -> None:
        if type(line) is not str or "\n" in line or "\r" in line:
            raise wire.CodexTransportError("Codex stdio write was not one JSONL frame")
        try:
            encoded = line.encode("utf-8")
        except UnicodeError:
            raise wire.CodexTransportError("Codex stdio frame was not UTF-8") from None
        if len(encoded) > self._max_frame_bytes:
            raise wire.CodexTransportError("Codex stdio frame exceeded its byte limit")
        try:
            async with asyncio.timeout(self._write_timeout):
                async with self._write_lock:
                    self._require_open()
                    self._stdin.write(encoded + b"\n")
                    await self._stdin.drain()
        except asyncio.CancelledError:
            raise
        except Exception:
            raise wire.CodexTransportError("Codex stdio write failed") from None

    async def read_line(self, max_bytes: int) -> str:
        if type(max_bytes) is not int or max_bytes != self._max_frame_bytes:
            raise ValueError("read bound must exactly match the configured frame limit")
        try:
            async with self._read_lock:
                self._require_open()
                raw = await self._stdout.readuntil(b"\n")
        except asyncio.CancelledError:
            raise
        except asyncio.IncompleteReadError:
            raise CodexProcessExitedError(self._process.returncode) from None
        except asyncio.LimitOverrunError:
            raise wire.CodexTransportError("Codex stdio frame exceeded its byte limit") from None
        except wire.CodexAppServerError:
            raise
        except Exception:
            raise wire.CodexTransportError("Codex stdio read failed") from None
        frame = raw[:-1]
        if frame.endswith(b"\r"):
            frame = frame[:-1]
        if len(frame) > max_bytes:
            raise wire.CodexTransportError("Codex stdio frame exceeded its byte limit")
        try:
            return frame.decode("utf-8", errors="strict")
        except UnicodeError:
            raise wire.CodexTransportError("Codex stdio frame was not UTF-8") from None

    async def wait(self) -> int:
        return await self._process.wait()

    async def wait_stderr_drained(self) -> None:
        try:
            await asyncio.wait_for(asyncio.shield(self._stderr_task), self._close_timeout)
        except TimeoutError:
            self._stderr_task.cancel()
            await asyncio.gather(self._stderr_task, return_exceptions=True)

    async def aclose(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            failure = False
            try:
                failure = not await self._close_stdin()
                if not await self._wait_for_exit(self._close_timeout):
                    self._terminate()
                    if not await self._wait_for_exit(self._terminate_timeout):
                        self._kill()
                        if not await self._wait_for_exit(self._kill_timeout):
                            failure = True
                await self.wait_stderr_drained()
            except asyncio.CancelledError:
                self._kill()
                with contextlib.suppress(Exception):
                    await asyncio.shield(self._wait_for_exit(self._kill_timeout))
                raise
            except Exception:
                failure = True
                self._kill()
                with contextlib.suppress(Exception):
                    await self._wait_for_exit(self._kill_timeout)
            if failure:
                raise wire.CodexTransportError("Codex process cleanup did not complete cleanly")
            self._closed = True

    async def _discard_stderr(self) -> None:
        try:
            while await self._stderr.read(STDERR_CHUNK_BYTES):
                pass
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    async def _close_stdin(self) -> bool:
        try:
            self._stdin.close()
            await asyncio.wait_for(self._stdin.wait_closed(), self._close_timeout)
        except Exception:
            return False
        return True

    async def _wait_for_exit(self, timeout: float) -> bool:
        if self._process.returncode is not None:
            return True
        try:
            await asyncio.wait_for(asyncio.shield(self._process.wait()), timeout)
        except TimeoutError:
            return False
        return True

    def _terminate(self) -> None:
        if self._process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self._process.terminate()

    def _kill(self) -> None:
        if self._process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self._process.kill()

    def _require_open(self) -> None:
        if self._closed or self._process.returncode is not None:
            raise CodexProcessExitedError(self._process.returncode)
