"""Bounded read-only client for a locally supervised Codex App Server."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from boltrig.fleet.domain import CanonicalJSON, JSONValue

from . import codex_client_support as support
from . import codex_protocol as wire

logger = logging.getLogger(__name__)

_ResultT = TypeVar("_ResultT")

# A handler for a codex SERVER-INITIATED request: given the request, produce the
# response we write back. Injected at the composition root so the protocol client
# does not hard-code an approval policy ([2026] VJS-COUNTY 12). When absent, a
# server request is refused with a typed error - never a pump crash.
ServerRequestHandler = Callable[[wire.RequestMessage], Awaitable[wire.ResponseMessage]]


class CodexAppServerClient:
    """Correlate stable read-only calls without owning a process or network."""

    def __init__(
        self,
        transport: wire.AsyncLineTransport,
        *,
        client_name: str = "boltrig",
        client_title: str = "Boltrig",
        client_version: str = "0.1.0",
        request_timeout: float = 30.0,
        max_pending: int = 32,
        max_notifications: int = 256,
        max_notification_bytes: int = 4 * 1024 * 1024,
        response_history: int = 512,
        max_tombstones: int = 256,
        server_request_handler: ServerRequestHandler | None = None,
    ) -> None:
        self._request_timeout = support.validate_client_settings(
            (client_name, client_title, client_version),
            request_timeout,
            (
                max_pending,
                max_notifications,
                max_notification_bytes,
                response_history,
                max_tombstones,
            ),
        )
        if not isinstance(transport, wire.AsyncLineTransport):
            raise TypeError("transport must implement AsyncLineTransport")
        self._transport = transport
        self._identity = (client_name, client_title, client_version)
        self._notifications = support.NotificationBuffer(
            max_count=max_notifications, max_bytes=max_notification_bytes
        )
        self._tracker = support.CorrelationTracker(
            max_pending=max_pending,
            history_limit=response_history,
            tombstone_limit=max_tombstones,
        )
        self._writer = support.BoundedWriter(
            transport, self._tracker, request_timeout=self._request_timeout
        )
        self._state = wire.ClientState.NEW
        self._failure: wire.CodexAppServerError | None = None
        self._failure_event = asyncio.Event()
        self._allocation_lock = asyncio.Lock()
        self._reader_task: asyncio.Task[None] | None = None
        self._transport_closed = False
        self._server_request_handler = server_request_handler
        self._server_request_tasks: set[asyncio.Task[None]] = set()

    @property
    def state(self) -> wire.ClientState:
        return self._state

    @property
    def transport_closed(self) -> bool:
        return self._transport_closed

    @property
    def queued_notification_bytes(self) -> int:
        return self._notifications.queued_bytes

    async def initialize(self) -> wire.CallReceipt:
        if self._state is not wire.ClientState.NEW:
            raise wire.ProtocolStateError("Codex App Server connection cannot be re-initialized")
        self._state = wire.ClientState.INITIALIZING
        self._reader_task = asyncio.create_task(self._reader_loop(), name="codex-app-server-reader")
        deadline = self._writer.deadline()
        name, title, version = self._identity
        params = CanonicalJSON.from_mapping(
            {
                "clientInfo": {"name": name, "title": title, "version": version},
                "capabilities": {"experimentalApi": False},
            }
        )
        try:
            result = await self._call(
                "initialize", params, deadline=deadline, during_initialize=True
            )
            receipt = self._validate(lambda: support.validate_initialize(result))
            initialized = wire.encode_notification(wire.NotificationMessage("initialized"))
            await self._writer.send_notification("initialized", initialized, deadline)
        except asyncio.CancelledError:
            await self._abort_initialization(
                wire.ProtocolStateError("Codex initialization was cancelled")
            )
            raise
        except wire.CodexAppServerError as exc:
            await self._abort_initialization(exc)
            raise
        self._state = wire.ClientState.READY
        return receipt

    async def thread_start(
        self,
        *,
        cwd: str,
        model: str | None = None,
        sandbox: str = "read-only",
        approval_policy: str = "never",
        base_instructions: str | None = None,
        developer_instructions: str | None = None,
    ) -> wire.ThreadResult:
        support.require_read_only_policy(sandbox, approval_policy)
        exact_cwd = support.require_absolute_cwd(cwd)
        exact_model = None if model is None else support.require_identifier("model", model)
        params: dict[str, JSONValue] = {
            "approvalPolicy": "never",
            "cwd": exact_cwd,
            "ephemeral": True,
            "sandbox": "read-only",
        }
        support.add_optional_text(params, "model", exact_model)
        support.add_optional_text(params, "baseInstructions", base_instructions)
        support.add_optional_text(params, "developerInstructions", developer_instructions)
        result = await self._call("thread/start", CanonicalJSON.from_mapping(params))
        return self._validate(
            lambda: support.validate_thread_policy_result(
                result,
                expected_thread_id=None,
                expected_cwd=exact_cwd,
                expected_model=exact_model,
            )
        )

    async def thread_resume(
        self,
        thread_id: str,
        *,
        cwd: str,
        model: str | None = None,
        sandbox: str = "read-only",
        approval_policy: str = "never",
    ) -> wire.ThreadResult:
        support.require_read_only_policy(sandbox, approval_policy)
        exact_thread = support.require_identifier("thread id", thread_id)
        exact_cwd = support.require_absolute_cwd(cwd)
        exact_model = None if model is None else support.require_identifier("model", model)
        params: dict[str, JSONValue] = {
            "approvalPolicy": "never",
            "cwd": exact_cwd,
            "sandbox": "read-only",
            "threadId": exact_thread,
        }
        support.add_optional_text(params, "model", exact_model)
        result = await self._call("thread/resume", CanonicalJSON.from_mapping(params))
        return self._validate(
            lambda: support.validate_thread_policy_result(
                result,
                expected_thread_id=exact_thread,
                expected_cwd=exact_cwd,
                expected_model=exact_model,
            )
        )

    async def thread_read(
        self, thread_id: str, *, include_turns: bool = False
    ) -> wire.ThreadResult:
        exact_thread = support.require_identifier("thread id", thread_id)
        params = CanonicalJSON.from_mapping(
            {
                "includeTurns": support.require_bool("include_turns", include_turns),
                "threadId": exact_thread,
            }
        )
        result = await self._call("thread/read", params)
        return self._validate(lambda: support.validate_thread_read(result, exact_thread))

    async def turn_start(
        self,
        thread_id: str,
        *,
        prompt: str,
        client_user_message_id: str,
        output_schema: CanonicalJSON | None = None,
    ) -> wire.TurnResult:
        params: dict[str, JSONValue] = {
            "clientUserMessageId": support.require_identifier(
                "client user message id", client_user_message_id
            ),
            "input": [{"type": "text", "text": support.require_prompt(prompt)}],
            "threadId": support.require_identifier("thread id", thread_id),
        }
        schema = support.require_output_schema(output_schema)
        if schema is not None:
            params["outputSchema"] = schema.to_mapping()
        result = await self._call("turn/start", CanonicalJSON.from_mapping(params))
        return self._validate(
            lambda: support.validate_turn_result(result, expected_turn_id=None, nested=True)
        )

    async def turn_steer(
        self,
        thread_id: str,
        *,
        expected_turn_id: str,
        prompt: str,
        client_user_message_id: str,
    ) -> wire.TurnResult:
        exact_turn = support.require_identifier("expected turn id", expected_turn_id)
        params = CanonicalJSON.from_mapping(
            {
                "clientUserMessageId": support.require_identifier(
                    "client user message id", client_user_message_id
                ),
                "expectedTurnId": exact_turn,
                "input": [{"type": "text", "text": support.require_prompt(prompt)}],
                "threadId": support.require_identifier("thread id", thread_id),
            }
        )
        result = await self._call("turn/steer", params)
        return self._validate(
            lambda: support.validate_turn_result(result, expected_turn_id=exact_turn, nested=False)
        )

    async def turn_interrupt(self, thread_id: str, turn_id: str) -> wire.CallReceipt:
        params = CanonicalJSON.from_mapping(
            {
                "threadId": support.require_identifier("thread id", thread_id),
                "turnId": support.require_identifier("turn id", turn_id),
            }
        )
        result = await self._call("turn/interrupt", params)
        return self._validate(lambda: support.validate_empty_result(result))

    async def next_notification(self, *, timeout: float | None = None) -> wire.NotificationMessage:
        if timeout is not None and (
            type(timeout) not in {int, float} or not 0 <= timeout < float("inf")
        ):
            raise ValueError("notification timeout must be finite and non-negative")
        if not self._notifications.empty():
            return self._notifications.get_nowait()
        self._raise_if_stopped()
        get_task = asyncio.create_task(self._notifications.get())
        failed_task = asyncio.create_task(self._failure_event.wait())
        try:
            done, _pending = await asyncio.wait(
                {get_task, failed_task}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            if get_task in done:
                return get_task.result()
            if not done:
                raise TimeoutError("timed out waiting for a Codex notification")
            self._raise_if_stopped()
            raise wire.ProtocolStateError("Codex notification stream stopped")  # pragma: no cover
        finally:
            for task in (get_task, failed_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(get_task, failed_task, return_exceptions=True)

    async def aclose(self) -> None:
        if self._state is not wire.ClientState.CLOSED:
            self._state = wire.ClientState.CLOSED
            closed = wire.ProtocolStateError("Codex App Server connection is closed")
            if self._failure is None:
                self._failure = closed
            self._failure_event.set()
            self._tracker.fail_all(closed)
            await support.stop_task(self._reader_task)
            await self._drain_server_request_tasks()
        await self._close_transport()

    async def _drain_server_request_tasks(self) -> None:
        """Cancel and await any in-flight server-request answers on close."""
        tasks = list(self._server_request_tasks)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _call(
        self,
        method: str,
        params: CanonicalJSON,
        *,
        deadline: float | None = None,
        during_initialize: bool = False,
    ) -> wire.CorrelatedResult:
        self._ensure_request_state(during_initialize=during_initialize)
        expiry = self._writer.deadline() if deadline is None else deadline
        loop = asyncio.get_running_loop()
        async with self._allocation_lock:
            self._ensure_request_state(during_initialize=during_initialize)
            future: asyncio.Future[wire.ResponseMessage] = loop.create_future()
            request_id = self._tracker.allocate(method, future)
        line = support.encode_allocated_request(
            self._tracker, wire.RequestMessage(request_id, method, params)
        )
        try:
            await self._writer.send_request(request_id, method, line, expiry)
        except wire.CodexTransportError as exc:
            self._mark_failed(exc)
            raise
        response = await self._wait_for_response(request_id, method, future, expiry)
        if response.error is not None:
            raise wire.CodexRemoteError(
                method=method, request_id=request_id, code=response.error.code
            )
        if response.result is None:  # pragma: no cover - enforced by ResponseMessage
            raise wire.MalformedMessageError("Codex response has no result")
        return wire.CorrelatedResult(request_id, method, response.result)

    async def _wait_for_response(
        self,
        request_id: int,
        method: str,
        future: asyncio.Future[wire.ResponseMessage],
        deadline: float,
    ) -> wire.ResponseMessage:
        try:
            response_timeout = self._writer.remaining(deadline)
            return await asyncio.wait_for(asyncio.shield(future), response_timeout)
        except TimeoutError:
            self._tracker.retire(request_id)
            raise wire.RequestTimeoutError(method=method, request_id=request_id) from None
        except asyncio.CancelledError:
            self._tracker.retire(request_id)
            raise

    async def _reader_loop(self) -> None:
        try:
            while True:
                try:
                    line = await self._transport.read_line(wire.MAX_LINE_BYTES)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    raise wire.CodexTransportError(
                        "failed to read from Codex line transport"
                    ) from None
                message = wire.decode_message(line)
                if isinstance(message, wire.ResponseMessage):
                    self._receive_response(message)
                elif isinstance(message, wire.NotificationMessage):
                    self._notifications.put(message, len(line.encode("utf-8")))
                else:
                    # A server-initiated request (e.g. codex's per-tool-call
                    # item/tool/requestUserInput approval) is ANSWERED on a side
                    # task so the single reader never blocks; it must NEVER crash
                    # the pump ([2026] VJS-COUNTY 12, and AGENTS.md graceful
                    # degradation). Absent a handler it is refused with a typed
                    # error, not a terminal.
                    self._dispatch_server_request(message)
        except asyncio.CancelledError:
            raise
        except wire.CodexAppServerError as exc:
            self._mark_failed(exc)
        except Exception:
            self._mark_failed(wire.CodexTransportError("Codex reader stopped unexpectedly"))

    def _receive_response(self, response: wire.ResponseMessage) -> None:
        pending = self._tracker.receive(response)
        if pending is not None and not pending.future.done():
            pending.future.set_result(response)

    def _dispatch_server_request(self, request: wire.RequestMessage) -> None:
        task = asyncio.create_task(
            self._answer_server_request(request),
            name=f"codex-server-request-{request.request_id}",
        )
        self._server_request_tasks.add(task)
        task.add_done_callback(self._server_request_tasks.discard)

    async def _answer_server_request(self, request: wire.RequestMessage) -> None:
        try:
            if self._server_request_handler is not None:
                response = await self._server_request_handler(request)
            else:
                response = wire.ResponseMessage(
                    request_id=request.request_id,
                    error=wire.RemoteErrorData(
                        code=-32601, message="server requests are not handled"
                    ),
                )
            line = wire.encode_response(response)
            await self._writer.send_response(
                request.request_id, line, self._writer.deadline()
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            # Answering must never crash the pump: a failed write leaves the
            # request unanswered (codex auto-resolves it on its own timer), which
            # is strictly better than a terminal. Content-free: only the id.
            logger.warning(
                "codex server-request answer failed (id=%s)", request.request_id
            )

    def _validate(self, callback: Callable[[], _ResultT]) -> _ResultT:
        try:
            return callback()
        except wire.MalformedMessageError as exc:
            self._mark_failed(exc)
            raise

    def _mark_failed(self, error: wire.CodexAppServerError) -> None:
        if self._state is wire.ClientState.CLOSED or self._failure is not None:
            return
        self._failure = error
        self._state = wire.ClientState.FAILED
        self._failure_event.set()
        self._tracker.fail_all(error)
        reader = self._reader_task
        if reader is not None and reader is not asyncio.current_task() and not reader.done():
            reader.cancel()

    async def _abort_initialization(self, error: wire.CodexAppServerError) -> None:
        self._mark_failed(error)
        await support.stop_task(self._reader_task)
        try:
            await self._close_transport()
        except wire.CodexTransportError:
            pass

    async def _close_transport(self) -> None:
        if self._transport_closed:
            return
        await support.close_transport(self._transport, timeout=self._request_timeout)
        self._transport_closed = True

    def _ensure_request_state(self, *, during_initialize: bool) -> None:
        expected = wire.ClientState.INITIALIZING if during_initialize else wire.ClientState.READY
        if self._state is expected:
            return
        self._raise_if_stopped()
        raise wire.ProtocolStateError("Codex request requires a completed initialize handshake")

    def _raise_if_stopped(self) -> None:
        if self._failure is not None:
            raise self._failure
        if self._state is wire.ClientState.CLOSED:
            raise wire.ProtocolStateError("Codex App Server connection is closed")
