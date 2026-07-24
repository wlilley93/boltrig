"""Strict, payload-safe JSONL primitives for Codex App Server 0.144.3."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import NoReturn, Protocol, TypeAlias, runtime_checkable

from boltrig.fleet.domain import CanonicalJSON, JSONValue

MAX_LINE_BYTES = 1024 * 1024


class CodexAppServerError(RuntimeError):
    """Base error whose text never includes request or response payloads."""


class CodexProtocolError(CodexAppServerError):
    """The peer violated the negotiated App Server protocol."""


class MalformedMessageError(CodexProtocolError):
    """A wire message was not an unambiguous omitted-jsonrpc envelope."""


class ProtocolStateError(CodexAppServerError):
    """An operation was attempted in the wrong connection state."""


class PendingRequestsFullError(CodexAppServerError):
    """The bounded in-flight request capacity has been exhausted."""


class NotificationQueueFullError(CodexProtocolError):
    """A bounded notification count or byte budget was exhausted."""


class RequestTimeoutError(CodexAppServerError):
    """A request did not complete its bounded send/response cycle in time."""

    def __init__(self, *, method: str, request_id: int) -> None:
        self.method = method
        self.request_id = request_id
        super().__init__(f"Codex request {request_id} ({method}) timed out")


class UnknownResponseIdError(CodexProtocolError):
    """A response did not correlate to an in-flight or retired request."""

    def __init__(self, request_id: int) -> None:
        self.request_id = request_id
        super().__init__(f"Codex response id {request_id} is not recognized")


class DuplicateResponseIdError(CodexProtocolError):
    """A peer answered the same live or retired request more than once."""

    def __init__(self, request_id: int) -> None:
        self.request_id = request_id
        super().__init__(f"Codex response id {request_id} was already completed")


class UnexpectedServerRequestError(CodexProtocolError):
    """Typed server requests are not implemented by the first read-only client."""

    def __init__(self) -> None:
        super().__init__("unsupported server-initiated Codex request")


class CodexTransportError(CodexAppServerError):
    """The local line transport failed without exposing its possibly-secret detail."""


class CodexRemoteError(CodexAppServerError):
    """A correlated App Server request returned an error envelope."""

    def __init__(self, *, method: str, request_id: int, code: int) -> None:
        self.method = method
        self.request_id = request_id
        self.code = code
        super().__init__(f"Codex request {request_id} ({method}) failed with code {code}")


@runtime_checkable
class AsyncLineTransport(Protocol):
    """Allocation-bounded local line seam implemented by stdio/private sockets.

    ``read_line`` must stop buffering and raise before retaining more than
    ``max_bytes``. The client performs a second codec bound check in defense in
    depth. ``write_line`` must emit one frame atomically or raise.
    """

    async def write_line(self, line: str) -> None: ...

    async def read_line(self, max_bytes: int) -> str: ...

    async def aclose(self) -> None: ...


@dataclass(frozen=True)
class RequestMessage:
    request_id: int
    method: str
    params: CanonicalJSON = field(default_factory=CanonicalJSON.empty_mapping)


@dataclass(frozen=True)
class NotificationMessage:
    method: str
    params: CanonicalJSON = field(default_factory=CanonicalJSON.empty_mapping)


@dataclass(frozen=True)
class RemoteErrorData:
    code: int
    message: str = field(repr=False)
    data: CanonicalJSON | None = field(default=None, repr=False)


@dataclass(frozen=True)
class ResponseMessage:
    request_id: int
    result: CanonicalJSON | None = None
    error: RemoteErrorData | None = None

    def __post_init__(self) -> None:
        if (self.result is None) == (self.error is None):
            raise ValueError("a response must contain exactly one of result or error")


WireMessage: TypeAlias = RequestMessage | ResponseMessage | NotificationMessage


class ClientState(str, Enum):
    NEW = "new"
    INITIALIZING = "initializing"
    READY = "ready"
    FAILED = "failed"
    CLOSED = "closed"


@dataclass(frozen=True)
class CorrelatedResult:
    request_id: int
    method: str
    payload: CanonicalJSON


@dataclass(frozen=True)
class ThreadResult:
    request_id: int
    method: str
    thread_id: str
    payload: CanonicalJSON


@dataclass(frozen=True)
class TurnResult:
    request_id: int
    method: str
    turn_id: str
    payload: CanonicalJSON


@dataclass(frozen=True)
class CallReceipt:
    request_id: int
    method: str
    payload: CanonicalJSON


def _invalid_constant(_value: str) -> NoReturn:
    raise ValueError("non-finite JSON number")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _json_value(value: object) -> JSONValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("non-finite JSON number")
        return value
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        if not all(type(key) is str for key in value):
            raise ValueError("JSON object key is not a string")
        return {str(key): _json_value(item) for key, item in value.items()}
    raise ValueError("value is not JSON-compatible")


def _identifier(label: str, value: object) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"invalid {label}")
    return value


def _request_id(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("invalid request id")
    return value


def _params(value: object) -> CanonicalJSON:
    if not isinstance(value, dict):
        raise ValueError("params must be an object")
    converted = _json_value(value)
    if not isinstance(converted, dict):  # pragma: no cover - narrowed above
        raise ValueError("params must be an object")
    return CanonicalJSON.from_mapping(converted)


def _decode_error(value: object) -> RemoteErrorData:
    if not isinstance(value, dict) or not {"code", "message"} <= set(value):
        raise ValueError("malformed error object")
    if set(value) - {"code", "message", "data"}:
        raise ValueError("unexpected error object fields")
    code = value["code"]
    message = value["message"]
    if type(code) is not int or type(message) is not str:
        raise ValueError("malformed error object")
    data = None
    if "data" in value:
        data = CanonicalJSON.from_value(_json_value(value["data"]))
    return RemoteErrorData(code=code, message=message, data=data)


def _decode_object(value: dict[str, object]) -> WireMessage:
    if "jsonrpc" in value:
        raise ValueError("jsonrpc header must be omitted")
    if "method" in value:
        expected = {"method", "params"} | ({"id"} if "id" in value else set())
        if set(value) != expected:
            raise ValueError("malformed request or notification envelope")
        method = _identifier("method", value["method"])
        params = _params(value["params"])
        if "id" in value:
            return RequestMessage(_request_id(value["id"]), method, params)
        return NotificationMessage(method, params)
    if "id" not in value or set(value) not in ({"id", "result"}, {"id", "error"}):
        raise ValueError("malformed response envelope")
    request_id = _request_id(value["id"])
    if "error" in value:
        return ResponseMessage(request_id=request_id, error=_decode_error(value["error"]))
    return ResponseMessage(
        request_id=request_id,
        result=CanonicalJSON.from_value(_json_value(value["result"])),
    )


def _byte_limit(value: object) -> int:
    if type(value) is not int or value < 1:
        raise ValueError("max_bytes must be a positive integer")
    return value


def decode_message(line: str, *, max_bytes: int = MAX_LINE_BYTES) -> WireMessage:
    """Decode one JSONL frame without retaining or echoing malformed payloads."""

    limit = _byte_limit(max_bytes)
    if type(line) is not str or len(line.encode("utf-8")) > limit:
        raise MalformedMessageError("malformed Codex App Server message")
    candidate = line.removesuffix("\n").removesuffix("\r")
    if not candidate or "\n" in candidate or "\r" in candidate:
        raise MalformedMessageError("malformed Codex App Server message")
    try:
        raw: object = json.loads(
            candidate,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_invalid_constant,
        )
        if not isinstance(raw, dict):
            raise ValueError("message must be an object")
        return _decode_object(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise MalformedMessageError("malformed Codex App Server message") from None


def _encode(value: dict[str, JSONValue], *, max_bytes: int) -> str:
    limit = _byte_limit(max_bytes)
    try:
        line = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError):
        raise MalformedMessageError("cannot encode Codex App Server message") from None
    if len(line.encode("utf-8")) > limit:
        raise MalformedMessageError("Codex App Server message exceeds the line limit")
    return line


def encode_request(message: RequestMessage, *, max_bytes: int = MAX_LINE_BYTES) -> str:
    _request_id(message.request_id)
    _identifier("method", message.method)
    value: dict[str, JSONValue] = {
        "id": message.request_id,
        "method": message.method,
        "params": message.params.to_mapping(),
    }
    return _encode(value, max_bytes=max_bytes)


def encode_notification(message: NotificationMessage, *, max_bytes: int = MAX_LINE_BYTES) -> str:
    _identifier("method", message.method)
    value: dict[str, JSONValue] = {
        "method": message.method,
        "params": message.params.to_mapping(),
    }
    return _encode(value, max_bytes=max_bytes)


def encode_response(message: ResponseMessage, *, max_bytes: int = MAX_LINE_BYTES) -> str:
    """Encode a client->server RESPONSE to a server-initiated request.

    Codex's App Server can initiate a request to the client (e.g.
    ``item/tool/requestUserInput``, a per-tool-call approval); the client answers
    by writing a response keyed to the SAME ``id``. The envelope mirrors the
    decoder's contract (:func:`_decode_object`): exactly ``{"id","result"}`` or
    ``{"id","error"}``, ``jsonrpc`` omitted. ``ResponseMessage.__post_init__``
    already guarantees exactly one of result/error is set.
    """
    _request_id(message.request_id)
    value: dict[str, JSONValue]
    if message.error is not None:
        error: dict[str, JSONValue] = {
            "code": message.error.code,
            "message": message.error.message,
        }
        if message.error.data is not None:
            error["data"] = message.error.data.to_value()
        value = {"id": message.request_id, "error": error}
    else:
        assert message.result is not None  # guaranteed by __post_init__
        value = {"id": message.request_id, "result": message.result.to_mapping()}
    return _encode(value, max_bytes=max_bytes)
