"""Allocation-bounded HTTP response buffering for outbound adapters."""

from __future__ import annotations

from typing import Any

import httpx

from boltrig.adapters.base import AdapterError, ErrorClass


MAX_JSON_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_BINARY_RESPONSE_BYTES = 32 * 1024 * 1024


class ResponseBoundaryError(RuntimeError):
    """An upstream response could not be represented inside its fixed bound."""


class ResponseBodyTooLarge(ResponseBoundaryError):
    """An upstream response exceeded the caller's allocation ceiling."""


class UnsupportedResponseEncoding(ResponseBoundaryError):
    """An upstream ignored the identity request and sent encoded bytes."""


def _content_length(headers: httpx.Headers) -> int | None:
    raw = headers.get("content-length")
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise ResponseBoundaryError("upstream returned an invalid content length") from exc
    if value < 0:
        raise ResponseBoundaryError("upstream returned an invalid content length")
    return value


async def _read_body(
    response: httpx.Response,
    *,
    max_bytes: int,
    truncate: bool,
    declared_length: int | None,
) -> tuple[bytes, bool]:
    body = bytearray()
    truncated = bool(
        truncate and declared_length is not None and declared_length > max_bytes
    )
    if response.is_stream_consumed:
        consumed = response.content
        if len(consumed) > max_bytes and not truncate:
            raise ResponseBodyTooLarge("upstream response exceeded the bounded limit")
        return consumed[:max_bytes], truncated or len(consumed) > max_bytes
    async for chunk in response.aiter_raw():
        if not chunk:
            continue
        remaining = max_bytes - len(body)
        if len(chunk) > remaining:
            if not truncate:
                raise ResponseBodyTooLarge(
                    "upstream response exceeded the bounded limit"
                )
            body.extend(chunk[:remaining])
            truncated = True
            break
        body.extend(chunk)
        if truncated and len(body) == max_bytes:
            break
    return bytes(body), truncated


async def bounded_http_response(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_bytes: int,
    truncate: bool = False,
    **kwargs: Any,
) -> tuple[httpx.Response, bool]:
    """Send one request and buffer no more than ``max_bytes`` raw body bytes.

    Transparent decompression is deliberately disabled.  A compressed response
    can allocate its decoded size before an application-level limit sees it, so
    every request asks for identity and a server that ignores that request is
    refused before body iteration.  ``truncate`` is reserved for web.fetch,
    whose public contract intentionally returns a prefix; all other callers fail
    closed when the fixed boundary is exceeded.
    """
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")

    headers = httpx.Headers(kwargs.pop("headers", None) or {})
    headers["Accept-Encoding"] = "identity"
    request = client.build_request(method, url, headers=headers, **kwargs)
    response = await client.send(request, stream=True)
    try:
        encoding = response.headers.get("content-encoding", "").strip().lower()
        if encoding not in {"", "identity"}:
            raise UnsupportedResponseEncoding(
                "upstream returned an unsupported content encoding"
            )
        declared_length = _content_length(response.headers)
        if not truncate and declared_length is not None and declared_length > max_bytes:
            raise ResponseBodyTooLarge("upstream response exceeded the bounded limit")

        body, truncated = await _read_body(
            response,
            max_bytes=max_bytes,
            truncate=truncate,
            declared_length=declared_length,
        )

        buffered_headers = httpx.Headers(response.headers)
        for name in ("content-encoding", "content-length", "transfer-encoding"):
            if name in buffered_headers:
                del buffered_headers[name]
        buffered_headers["content-length"] = str(len(body))
        buffered = httpx.Response(
            response.status_code,
            headers=buffered_headers,
            content=body,
            request=request,
        )
        return buffered, truncated
    finally:
        await response.aclose()


def bounded_response_error() -> AdapterError:
    """Return the shared content-free typed adapter error."""
    return AdapterError(
        ErrorClass.UNAVAILABLE,
        "upstream response exceeded its safety boundary",
        retryable=False,
    )
