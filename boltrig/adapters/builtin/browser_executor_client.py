"""Private Unix-socket carriage for the governed browser adapter.

The kernel keeps consequence/approval/tenant policy.  This carriage moves only
the already-admitted fixed browser verb to the isolated Chromium container; it
does not expose a second public API, raw CDP, or caller-selected code.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from boltrig.adapters.base import AdapterError, ErrorClass, Result
from boltrig.models import InvocationContext

_MAX_REQUEST_BYTES = 32 * 1024
_MAX_RESPONSE_BYTES = 3 * 1024 * 1024


async def execute_over_socket(
    socket_path: str,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
    *,
    timeout: float,
) -> Result:
    body = {
        "verb": verb,
        "params": params,
        "context": {
            "tenant_id": str(context.tenant_id),
            "owner_id": str(context.on_behalf_of or context.actor),
        },
    }
    encoded = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(encoded) > _MAX_REQUEST_BYTES:
        return Result.failure(AdapterError(ErrorClass.INVALID, "browser request is too large"))
    transport = httpx.AsyncHTTPTransport(uds=socket_path, retries=0)
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://browser-executor",
            follow_redirects=False,
            timeout=httpx.Timeout(timeout),
            trust_env=False,
        ) as client:
            async with client.stream(
                "POST",
                "/v1/execute",
                content=encoded,
                headers={
                    "accept-encoding": "identity",
                    "content-type": "application/json",
                    "x-boltrig-browser-protocol": "1",
                },
            ) as response:
                payload = await _bounded_response(response)
    except (httpx.HTTPError, OSError):
        return Result.failure(
            AdapterError(ErrorClass.UNAVAILABLE, "browser executor is unavailable", retryable=True)
        )
    return _decode_result(payload)


async def executor_health(socket_path: str, *, timeout: float) -> str:
    transport = httpx.AsyncHTTPTransport(uds=socket_path, retries=0)
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://browser-executor",
            follow_redirects=False,
            timeout=httpx.Timeout(timeout),
            trust_env=False,
        ) as client:
            response = await client.get("/health")
        return "ok" if response.status_code == 200 else "down"
    except (httpx.HTTPError, OSError):
        return "down"


async def _bounded_response(response: httpx.Response) -> bytes:
    if response.status_code != 200:
        raise httpx.HTTPStatusError(
            "browser executor refused request", request=response.request, response=response
        )
    if response.headers.get("content-encoding", "identity").lower() not in {"", "identity"}:
        raise httpx.DecodingError("browser executor response encoding is not allowed")
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_raw():
        total += len(chunk)
        if total > _MAX_RESPONSE_BYTES:
            raise httpx.DecodingError("browser executor response is too large")
        chunks.append(chunk)
    return b"".join(chunks)


def _decode_result(payload: bytes) -> Result:
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, ValueError):
        return Result.failure(AdapterError(ErrorClass.INTERNAL, "invalid browser executor response"))
    if not isinstance(document, dict) or set(document) - {"ok", "output", "error"}:
        return Result.failure(AdapterError(ErrorClass.INTERNAL, "invalid browser executor response"))
    if document.get("ok") is True and isinstance(document.get("output"), dict):
        return Result.success(document["output"])
    error = document.get("error")
    if not isinstance(error, dict):
        return Result.failure(AdapterError(ErrorClass.INTERNAL, "invalid browser executor response"))
    try:
        error_class = ErrorClass(str(error.get("class") or "internal"))
    except ValueError:
        error_class = ErrorClass.INTERNAL
    return Result.failure(
        AdapterError(
            error_class,
            _safe_error_message(error.get("message")),
            retryable=bool(error.get("retryable")) and error_class is ErrorClass.UNAVAILABLE,
        )
    )


def _safe_error_message(value: Any) -> str:
    message = str(value or "browser executor refused the request")
    return message[:240] if message.isascii() else "browser executor refused the request"
