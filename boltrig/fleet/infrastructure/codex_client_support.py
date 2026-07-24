"""Bounded state and validation helpers for the read-only Codex client."""

from __future__ import annotations

import asyncio
import math
import posixpath
from collections import deque
from dataclasses import dataclass
from typing import cast

from boltrig.fleet.domain import CanonicalJSON, JSONValue

from . import codex_protocol as wire


@dataclass
class PendingRequest:
    method: str
    future: asyncio.Future[wire.ResponseMessage]


@dataclass(frozen=True)
class _QueuedNotification:
    message: wire.NotificationMessage
    byte_size: int


class CorrelationTracker:
    """Bound pending IDs, completed-ID history, and late-response tombstones."""

    def __init__(self, *, max_pending: int, history_limit: int, tombstone_limit: int) -> None:
        self._max_pending = max_pending
        self._history_limit = history_limit
        self._tombstone_limit = tombstone_limit
        self._pending: dict[int, PendingRequest] = {}
        self._completed: deque[int] = deque()
        self._completed_set: set[int] = set()
        self._tombstones: deque[int] = deque()
        self._tombstone_set: set[int] = set()
        self._next_id = 1

    def allocate(self, method: str, future: asyncio.Future[wire.ResponseMessage]) -> int:
        if len(self._pending) >= self._max_pending:
            raise wire.PendingRequestsFullError("Codex pending request queue is full")
        request_id = self._next_id
        self._next_id += 1
        self._pending[request_id] = PendingRequest(method, future)
        return request_id

    def remove_unsent(self, request_id: int) -> None:
        pending = self._pending.pop(request_id, None)
        if pending is not None and not pending.future.done():
            pending.future.cancel()

    def retire(self, request_id: int) -> None:
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        if not pending.future.done():
            pending.future.cancel()
        self._tombstones.append(request_id)
        self._tombstone_set.add(request_id)
        if len(self._tombstones) > self._tombstone_limit:
            expired = self._tombstones.popleft()
            self._tombstone_set.remove(expired)

    def receive(self, response: wire.ResponseMessage) -> PendingRequest | None:
        request_id = response.request_id
        if request_id in self._completed_set:
            raise wire.DuplicateResponseIdError(request_id)
        if request_id in self._tombstone_set:
            self._tombstone_set.remove(request_id)
            self._tombstones.remove(request_id)
            self._remember_completed(request_id)
            return None
        pending = self._pending.pop(request_id, None)
        if pending is None:
            raise wire.UnknownResponseIdError(request_id)
        self._remember_completed(request_id)
        return pending

    def fail_all(self, error: wire.CodexAppServerError) -> None:
        pending = tuple(self._pending.values())
        self._pending.clear()
        for item in pending:
            if not item.future.done():
                item.future.set_exception(error)

    def _remember_completed(self, request_id: int) -> None:
        self._completed.append(request_id)
        self._completed_set.add(request_id)
        if len(self._completed) > self._history_limit:
            expired = self._completed.popleft()
            self._completed_set.remove(expired)

    @property
    def tombstone_count(self) -> int:
        return len(self._tombstones)


class NotificationBuffer:
    """Bound notification retention by both item count and encoded byte size."""

    def __init__(self, *, max_count: int, max_bytes: int) -> None:
        self._queue: asyncio.Queue[_QueuedNotification] = asyncio.Queue(maxsize=max_count)
        self._max_bytes = max_bytes
        self._queued_bytes = 0

    def put(self, message: wire.NotificationMessage, byte_size: int) -> None:
        if type(byte_size) is not int or byte_size < 1:
            raise ValueError("notification byte size must be a positive integer")
        if self._queued_bytes + byte_size > self._max_bytes:
            raise wire.NotificationQueueFullError("Codex notification byte budget is full")
        try:
            self._queue.put_nowait(_QueuedNotification(message, byte_size))
        except asyncio.QueueFull:
            raise wire.NotificationQueueFullError("Codex notification queue is full") from None
        self._queued_bytes += byte_size

    def empty(self) -> bool:
        return self._queue.empty()

    def get_nowait(self) -> wire.NotificationMessage:
        return self._drain(self._queue.get_nowait())

    async def get(self) -> wire.NotificationMessage:
        return self._drain(await self._queue.get())

    def _drain(self, item: _QueuedNotification) -> wire.NotificationMessage:
        self._queued_bytes -= item.byte_size
        return item.message

    @property
    def queued_bytes(self) -> int:
        return self._queued_bytes


def encode_allocated_request(
    tracker: CorrelationTracker, request: wire.RequestMessage
) -> str:
    try:
        return wire.encode_request(request)
    except wire.CodexAppServerError:
        tracker.remove_unsent(request.request_id)
        raise


class BoundedWriter:
    """Serialize complete frames within one end-to-end request deadline."""

    def __init__(
        self,
        transport: wire.AsyncLineTransport,
        tracker: CorrelationTracker,
        *,
        request_timeout: float,
    ) -> None:
        self._transport = transport
        self._tracker = tracker
        self._request_timeout = request_timeout
        self._lock = asyncio.Lock()

    def deadline(self) -> float:
        return asyncio.get_running_loop().time() + self._request_timeout

    @staticmethod
    def remaining(deadline: float) -> float:
        value = deadline - asyncio.get_running_loop().time()
        if value <= 0:
            raise TimeoutError
        return value

    async def send_request(self, request_id: int, method: str, line: str, deadline: float) -> None:
        try:
            acquire_timeout = self.remaining(deadline)
            await asyncio.wait_for(self._lock.acquire(), acquire_timeout)
        except asyncio.CancelledError:
            self._tracker.remove_unsent(request_id)
            raise
        except TimeoutError:
            self._tracker.remove_unsent(request_id)
            raise wire.RequestTimeoutError(method=method, request_id=request_id) from None
        try:
            try:
                write_timeout = self.remaining(deadline)
                await asyncio.wait_for(self._transport.write_line(line), write_timeout)
            except asyncio.CancelledError:
                self._tracker.retire(request_id)
                raise
            except TimeoutError:
                self._tracker.retire(request_id)
                raise wire.RequestTimeoutError(method=method, request_id=request_id) from None
            except Exception:
                self._tracker.retire(request_id)
                raise wire.CodexTransportError("failed to write to Codex line transport") from None
        finally:
            self._lock.release()

    async def send_notification(self, method: str, line: str, deadline: float) -> None:
        # A notification is unsolicited and untracked (no id); on timeout Codex
        # models it as request_id 0.
        await self._send_untracked(line, deadline, method=method, request_id=0)

    async def send_response(self, request_id: int, line: str, deadline: float) -> None:
        """Write a client->server RESPONSE to a server-initiated request.

        A response is UNSOLICITED from our side and keyed to the INBOUND
        ``request_id``, so - unlike ``send_request`` - it never touches the
        correlation tracker (that maps OUR outbound ids). The deadline is the
        server-request's own answer deadline, not the client-request timeout.
        """
        await self._send_untracked(line, deadline, method="response", request_id=request_id)

    async def _send_untracked(
        self, line: str, deadline: float, *, method: str, request_id: int
    ) -> None:
        """Serialize one frame under the lock within ``deadline``, tracker-free.

        Shared by ``send_notification`` and ``send_response``: both write a frame
        that is not one of OUR outbound requests, so neither adjusts the
        correlation tracker (only ``send_request`` does)."""
        try:
            acquire_timeout = self.remaining(deadline)
            await asyncio.wait_for(self._lock.acquire(), acquire_timeout)
            try:
                write_timeout = self.remaining(deadline)
                await asyncio.wait_for(self._transport.write_line(line), write_timeout)
            finally:
                self._lock.release()
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            raise wire.RequestTimeoutError(method=method, request_id=request_id) from None
        except Exception:
            raise wire.CodexTransportError("failed to write to Codex line transport") from None


def validate_client_settings(
    identity: tuple[object, object, object],
    timeout: object,
    limits: tuple[object, object, object, object, object],
) -> float:
    for label, value in zip(("client name", "client title", "version"), identity, strict=True):
        require_identifier(label, value)
    if type(timeout) not in {int, float}:
        raise ValueError("request timeout must be positive and finite")
    numeric_timeout = cast(int | float, timeout)
    if not math.isfinite(numeric_timeout) or numeric_timeout <= 0:
        raise ValueError("request timeout must be positive and finite")
    for label, value in zip(
        (
            "max_pending",
            "max_notifications",
            "max_notification_bytes",
            "response_history",
            "max_tombstones",
        ),
        limits,
        strict=True,
    ):
        if type(value) is not int or value < 1:
            raise ValueError(f"{label} must be a positive integer")
    return float(numeric_timeout)


def require_identifier(label: str, value: object) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{label} must be a non-empty, trimmed string")
    return value


def require_prompt(value: object) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError("prompt must be a non-empty string")
    return value


def require_bool(label: str, value: object) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{label} must be a boolean")
    return value


def require_absolute_cwd(value: object) -> str:
    cwd = require_identifier("cwd", value)
    if (
        not posixpath.isabs(cwd)
        or cwd.startswith("//")
        or "\x00" in cwd
        or posixpath.normpath(cwd) != cwd
    ):
        raise ValueError("cwd must be a normalized absolute POSIX path")
    return cwd


def require_read_only_policy(sandbox: object, approval_policy: object) -> None:
    if type(sandbox) is not str or sandbox != "read-only":
        raise ValueError("the first Codex client requires read-only sandbox")
    if type(approval_policy) is not str or approval_policy != "never":
        raise ValueError("the first Codex client requires approval policy never")


def require_output_schema(value: object) -> CanonicalJSON | None:
    if value is not None and type(value) is not CanonicalJSON:
        raise TypeError("output_schema must be CanonicalJSON or None")
    return value


def add_optional_text(target: dict[str, JSONValue], key: str, value: str | None) -> None:
    if value is not None:
        target[key] = require_prompt(value)


async def stop_task(task: asyncio.Task[None] | None) -> None:
    if task is not None and not task.done():
        task.cancel()
    if task is not None:
        await asyncio.gather(task, return_exceptions=True)


async def close_transport(transport: wire.AsyncLineTransport, *, timeout: float) -> None:
    try:
        await asyncio.wait_for(transport.aclose(), timeout)
    except Exception:
        raise wire.CodexTransportError("failed to close Codex line transport") from None


def _mapping(result: wire.CorrelatedResult) -> dict[str, JSONValue]:
    try:
        return result.payload.to_mapping()
    except ValueError:
        raise wire.MalformedMessageError("malformed Codex method response") from None


def validate_initialize(result: wire.CorrelatedResult) -> wire.CallReceipt:
    payload = _mapping(result)
    try:
        require_absolute_cwd(payload["codexHome"])
        for field in ("platformFamily", "platformOs", "userAgent"):
            require_identifier(field, payload[field])
    except (KeyError, TypeError, ValueError):
        raise wire.MalformedMessageError("malformed Codex initialize response") from None
    return wire.CallReceipt(result.request_id, result.method, result.payload)


def _thread_id(payload: dict[str, JSONValue]) -> tuple[str, dict[str, JSONValue]]:
    thread = payload.get("thread")
    if not isinstance(thread, dict):
        raise ValueError("missing thread")
    return require_identifier("thread id", thread.get("id")), thread


def validate_thread_policy_result(
    result: wire.CorrelatedResult,
    *,
    expected_thread_id: str | None,
    expected_cwd: str,
    expected_model: str | None,
) -> wire.ThreadResult:
    payload = _mapping(result)
    try:
        thread_id, thread = _thread_id(payload)
        if expected_thread_id is not None and thread_id != expected_thread_id:
            raise ValueError("thread mismatch")
        if payload.get("approvalPolicy") != "never" or payload.get("cwd") != expected_cwd:
            raise ValueError("effective policy mismatch")
        model = require_identifier("model", payload.get("model"))
        if expected_model is not None and model != expected_model:
            raise ValueError("model mismatch")
        require_identifier("model provider", payload.get("modelProvider"))
        reviewer = payload.get("approvalsReviewer")
        if reviewer not in {"user", "auto_review", "guardian_subagent"}:
            raise ValueError("reviewer mismatch")
        sandbox = payload.get("sandbox")
        if not isinstance(sandbox, dict) or sandbox.get("type") != "readOnly":
            raise ValueError("sandbox mismatch")
        if sandbox.get("networkAccess", False) is not False:
            raise ValueError("network mismatch")
        if thread.get("cwd") != expected_cwd or thread.get("ephemeral") is not True:
            raise ValueError("thread policy mismatch")
    except (KeyError, TypeError, ValueError):
        raise wire.MalformedMessageError("malformed Codex thread policy response") from None
    return wire.ThreadResult(result.request_id, result.method, thread_id, result.payload)


def validate_thread_read(
    result: wire.CorrelatedResult, expected_thread_id: str
) -> wire.ThreadResult:
    payload = _mapping(result)
    try:
        thread_id, _thread = _thread_id(payload)
        if thread_id != expected_thread_id:
            raise ValueError("thread mismatch")
    except (TypeError, ValueError):
        raise wire.MalformedMessageError("malformed Codex thread response") from None
    return wire.ThreadResult(result.request_id, result.method, thread_id, result.payload)


def validate_turn_result(
    result: wire.CorrelatedResult, *, expected_turn_id: str | None, nested: bool
) -> wire.TurnResult:
    payload = _mapping(result)
    value: object
    if nested:
        turn = payload.get("turn")
        value = turn.get("id") if isinstance(turn, dict) else None
    else:
        value = payload.get("turnId")
    try:
        turn_id = require_identifier("turn id", value)
        if expected_turn_id is not None and turn_id != expected_turn_id:
            raise ValueError("turn mismatch")
    except (TypeError, ValueError):
        raise wire.MalformedMessageError("malformed Codex turn response") from None
    return wire.TurnResult(result.request_id, result.method, turn_id, result.payload)


def validate_empty_result(result: wire.CorrelatedResult) -> wire.CallReceipt:
    if _mapping(result):
        raise wire.MalformedMessageError("malformed Codex empty response")
    return wire.CallReceipt(result.request_id, result.method, result.payload)
