"""Single-reader, consumer-independent notification actor for one Codex phase."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from boltrig.fleet.domain import RuntimeEvent, RuntimeTurnRef

from . import codex_protocol as wire
from .codex_app_server import CodexAppServerClient
from .codex_runtime_event_state import CodexRuntimeProtocolError
from .codex_runtime_events import CodexEventTranslator, is_runtime_invalidation

MAX_BUFFERED_RUNTIME_EVENTS = 256
MAX_DEFERRED_NOTIFICATIONS = 64
MAX_PUMP_CHECKPOINTS = 8


@dataclass(frozen=True)
class CodexRuntimeTerminal:
    """Sanitized, durable first terminal cause for one runtime binding."""

    category: str
    message: str

    def exception(self) -> Exception:
        if self.category == "protocol":
            return CodexRuntimeProtocolError(self.message)
        return RuntimeError(self.message)


TerminalCallback = Callable[
    ["CodexRuntimeActor", CodexRuntimeTerminal], Awaitable[None]
]


class CodexRuntimeActor:
    """Own the sole post-preflight notification reader and bounded event queue."""

    def __init__(
        self,
        *,
        client: CodexAppServerClient,
        translator: CodexEventTranslator,
        on_terminal: TerminalCallback,
        max_buffered_events: int,
    ) -> None:
        if not 1 <= max_buffered_events <= MAX_BUFFERED_RUNTIME_EVENTS:
            raise ValueError("runtime event buffer is outside its bound")
        self._client = client
        self._translator = translator
        self._on_terminal = on_terminal
        self._events: asyncio.Queue[RuntimeEvent] = asyncio.Queue(max_buffered_events)
        self._checkpoints: asyncio.Queue[asyncio.Future[None]] = asyncio.Queue(
            MAX_PUMP_CHECKPOINTS
        )
        self._lock = asyncio.Lock()
        self._terminal_event = asyncio.Event()
        self._root_event = asyncio.Event()
        self._terminal: CodexRuntimeTerminal | None = None
        self._pump: asyncio.Task[None] | None = None
        self._turn_starting = False
        self._deferred: list[wire.NotificationMessage] = []
        self._stream_claimed = False

    @property
    def terminal(self) -> CodexRuntimeTerminal | None:
        return self._terminal

    @property
    def current_turn(self) -> RuntimeTurnRef | None:
        return self._translator.current_turn

    @property
    def latest_agent_message_text(self) -> str:
        """The latest turn's agentMessage text, for the read-back seam only."""
        return self._translator.latest_agent_message_text

    @property
    def pump_task(self) -> asyncio.Task[None] | None:
        return self._pump

    def start(self) -> None:
        if self._pump is not None:
            raise RuntimeError("Codex notification actor cannot be started twice")
        self._pump = asyncio.create_task(
            self._run(), name="codex-runtime-notification-pump"
        )

    async def wait_for_root(self, timeout: float) -> None:
        root_task = asyncio.create_task(self._root_event.wait())
        terminal_task = asyncio.create_task(self._terminal_event.wait())
        try:
            done, _ = await asyncio.wait(
                {root_task, terminal_task},
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if terminal_task in done:
                self.raise_if_terminal()
            if root_task not in done:
                terminal = CodexRuntimeTerminal(
                    "protocol", "Codex phase root start was not observed"
                )
                await self.fail(terminal)
                raise terminal.exception()
        finally:
            for task in (root_task, terminal_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(root_task, terminal_task, return_exceptions=True)

    async def checkpoint(self) -> None:
        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[None] = loop.create_future()
        terminal: CodexRuntimeTerminal | None
        async with self._lock:
            self.raise_if_terminal()
            if self._pump is None or self._pump.done():
                raise CodexRuntimeProtocolError("Codex notification actor is unavailable")
            try:
                self._checkpoints.put_nowait(waiter)
            except asyncio.QueueFull:
                terminal = CodexRuntimeTerminal(
                    "protocol", "Codex notification checkpoint queue overflowed"
                )
            else:
                terminal = None
        if terminal is not None:
            await self.fail(terminal)
            raise terminal.exception()
        await waiter
        self.raise_if_terminal()

    async def begin_turn_start(self) -> None:
        async with self._lock:
            self.raise_if_terminal()
            if self._turn_starting or self._translator.current_turn is not None:
                raise CodexRuntimeProtocolError("phase thread already has an active turn")
            self._turn_starting = True

    async def commit_turn_start(self, turn: RuntimeTurnRef) -> None:
        terminal: CodexRuntimeTerminal | None = None
        async with self._lock:
            self.raise_if_terminal()
            if not self._turn_starting:
                raise CodexRuntimeProtocolError("turn start has no active RPC")
            try:
                self._translator.bind_turn(turn)
                self._turn_starting = False
                deferred, self._deferred = self._deferred, []
                for notification in deferred:
                    self._emit_locked(notification)
            except CodexRuntimeProtocolError as exc:
                terminal = CodexRuntimeTerminal("protocol", str(exc))
        if terminal is not None:
            await self.fail(terminal)
            raise terminal.exception()

    async def assert_no_active_turn(self) -> None:
        async with self._lock:
            self.raise_if_terminal()
            if self._turn_starting or self._translator.current_turn is not None:
                raise CodexRuntimeProtocolError("phase thread has an active turn")

    async def assert_active_turn(self, turn: RuntimeTurnRef) -> None:
        async with self._lock:
            self.raise_if_terminal()
            if self._turn_starting or self._translator.current_turn != turn:
                raise CodexRuntimeProtocolError("target is not the active turn")

    async def claim_stream(self) -> None:
        async with self._lock:
            if self._stream_claimed:
                raise CodexRuntimeProtocolError("Codex event stream already has a consumer")
            self._stream_claimed = True

    async def release_stream(self) -> None:
        async with self._lock:
            self._stream_claimed = False

    async def next_event(self) -> RuntimeEvent:
        while True:
            self.raise_if_terminal()
            if not self._events.empty():
                return self._events.get_nowait()
            event_task = asyncio.create_task(self._events.get())
            terminal_task = asyncio.create_task(self._terminal_event.wait())
            try:
                done, _ = await asyncio.wait(
                    {event_task, terminal_task}, return_when=asyncio.FIRST_COMPLETED
                )
                if event_task in done:
                    return event_task.result()
                self.raise_if_terminal()
            finally:
                for task in (event_task, terminal_task):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(event_task, terminal_task, return_exceptions=True)

    async def fail(self, terminal: CodexRuntimeTerminal) -> None:
        async with self._lock:
            won = self._terminal is None
            if won:
                self._terminal = terminal
                self._terminal_event.set()
                self._wake_checkpoints_locked()
        if won:
            await self._on_terminal(self, terminal)

    def raise_if_terminal(self) -> None:
        if self._terminal is not None:
            raise self._terminal.exception()

    async def _run(self) -> None:
        notification_task: asyncio.Task[wire.NotificationMessage] | None = None
        checkpoint_task: asyncio.Task[asyncio.Future[None]] | None = None
        waiters: list[asyncio.Future[None]] = []
        try:
            notification_task = asyncio.create_task(self._client.next_notification())
            checkpoint_task = asyncio.create_task(self._checkpoints.get())
            while self._terminal is None:
                done, _ = await asyncio.wait(
                    {notification_task, checkpoint_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if notification_task in done:
                    notification = notification_task.result()
                    notification_task = None
                    if not await self._accept(notification):
                        break
                if checkpoint_task in done:
                    waiters.append(checkpoint_task.result())
                    checkpoint_task = asyncio.create_task(self._checkpoints.get())
                if notification_task is None:
                    while self._terminal is None:
                        try:
                            notification = await self._client.next_notification(timeout=0)
                        except TimeoutError:
                            break
                        if not await self._accept(notification):
                            break
                for waiter in waiters:
                    if not waiter.done():
                        waiter.set_result(None)
                waiters.clear()
                if self._terminal is None and notification_task is None:
                    notification_task = asyncio.create_task(
                        self._client.next_notification()
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.fail(
                CodexRuntimeTerminal("operation", "Codex notification pump failed")
            )
        finally:
            if (
                checkpoint_task is not None
                and checkpoint_task.done()
                and not checkpoint_task.cancelled()
            ):
                try:
                    waiters.append(checkpoint_task.result())
                except Exception:
                    pass
            for task in (notification_task, checkpoint_task):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(task for task in (notification_task, checkpoint_task) if task is not None),
                return_exceptions=True,
            )
            for waiter in waiters:
                if not waiter.done():
                    waiter.set_result(None)

    async def _accept(self, notification: wire.NotificationMessage) -> bool:
        terminal: CodexRuntimeTerminal | None = None
        async with self._lock:
            if self._terminal is not None:
                return False
            try:
                if is_runtime_invalidation(notification.method):
                    raise CodexRuntimeProtocolError(
                        "Codex quarantined runtime evidence was invalidated"
                    )
                if self._turn_starting:
                    if len(self._deferred) >= MAX_DEFERRED_NOTIFICATIONS:
                        raise CodexRuntimeProtocolError(
                            "Codex turn-start notification buffer overflowed"
                        )
                    self._deferred.append(notification)
                else:
                    self._emit_locked(notification)
            except CodexRuntimeProtocolError as exc:
                terminal = CodexRuntimeTerminal("protocol", str(exc))
        if terminal is not None:
            await self.fail(terminal)
            return False
        return True

    def _emit_locked(self, notification: wire.NotificationMessage) -> None:
        event = self._translator.translate(notification)
        try:
            self._events.put_nowait(event)
        except asyncio.QueueFull:
            raise CodexRuntimeProtocolError(
                "Codex normalized event queue overflowed"
            ) from None
        if self._translator.root_started:
            self._root_event.set()

    def _wake_checkpoints_locked(self) -> None:
        while not self._checkpoints.empty():
            waiter = self._checkpoints.get_nowait()
            if not waiter.done():
                waiter.set_result(None)


__all__ = [
    "CodexRuntimeActor",
    "CodexRuntimeTerminal",
    "MAX_BUFFERED_RUNTIME_EVENTS",
]
