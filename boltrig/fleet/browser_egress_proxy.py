"""Pinned public-network proxy for the isolated Chromium executor.

Chromium follows redirects and page-authored links after the kernel has checked
the address-bar URL.  This proxy is therefore the network boundary: every HTTP,
HTTPS and WebSocket connection is resolved once, refused when it targets
private/link-local/reserved space, and connected to the vetted IP.  It listens
on loopback only and exposes no configuration or general-purpose relay API.
"""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import SplitResult, urlsplit, urlunsplit

from boltrig.adapters.egress import EgressBlocked, resolve_and_vet

DEFAULT_PROXY_PORT = 9223
_MAX_HEADER_BYTES = 64 * 1024
_MAX_STREAM_BYTES = 128 * 1024 * 1024
_MAX_CONCURRENT_CONNECTIONS = 64
_HEADER_TIMEOUT = 10.0
_CONNECT_TIMEOUT = 8.0
_IDLE_TIMEOUT = 60.0
_ALLOWED_PORTS = frozenset({80, 443})
_METHOD = re.compile(r"^[A-Z]{3,10}$")
_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,80}$")
_DROP_HEADERS = frozenset(
    {"connection", "host", "keep-alive", "proxy-authorization", "proxy-connection"}
)


async def start_browser_egress_proxy(
    *,
    port: int = DEFAULT_PROXY_PORT,
    env: Mapping[str, str] | None = None,
) -> asyncio.AbstractServer:
    """Start the loopback-only proxy. A port of zero is allowed for tests."""
    if isinstance(port, bool) or port < 0 or port > 65535:
        raise ValueError("browser proxy port is invalid")
    policy = _network_policy(os.environ if env is None else env)
    active_connections = 0

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal active_connections
        if active_connections >= _MAX_CONCURRENT_CONNECTIONS:
            await _send_refusal(writer, 503, b"Service Unavailable")
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            return
        active_connections += 1
        try:
            await _handle_client(reader, writer, policy)
        finally:
            active_connections -= 1

    return await asyncio.start_server(
        handle,
        "127.0.0.1",
        port,
        limit=_MAX_HEADER_BYTES + 1,
    )


async def _handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    policy: dict[str, Any],
) -> None:
    upstream: asyncio.StreamWriter | None = None
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), _HEADER_TIMEOUT)
        if len(head) > _MAX_HEADER_BYTES:
            raise ValueError("request header too large")
        request = _parse_request(head)
        _host, vetted_ip = await asyncio.wait_for(
            asyncio.to_thread(resolve_and_vet, request[3], policy),
            _CONNECT_TIMEOUT,
        )
        upstream_reader, connected_upstream = await asyncio.wait_for(
            asyncio.open_connection(vetted_ip, request[2]),
            _CONNECT_TIMEOUT,
        )
        upstream = connected_upstream
        if request[0] == "CONNECT":
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        else:
            writer.write(b"")
            connected_upstream.write(_forward_head(head, request[1], request[4]))
            await asyncio.wait_for(connected_upstream.drain(), _CONNECT_TIMEOUT)
        await asyncio.wait_for(writer.drain(), _CONNECT_TIMEOUT)
        await _relay(reader, writer, upstream_reader, connected_upstream)
    except (EgressBlocked, ValueError):
        await _send_refusal(writer, 403, b"Forbidden")
    except (
        OSError,
        asyncio.IncompleteReadError,
        asyncio.LimitOverrunError,
        asyncio.TimeoutError,
    ):
        await _send_refusal(writer, 502, b"Bad Gateway")
    finally:
        if upstream is not None:
            upstream.close()
            try:
                await upstream.wait_closed()
            except OSError:
                pass
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass


def _parse_request(head: bytes) -> tuple[str, str, int, str, SplitResult | None]:
    try:
        lines = head[:-4].decode("iso-8859-1").split("\r\n")
        method, target, version = lines[0].split(" ")
    except (UnicodeDecodeError, ValueError, IndexError) as exc:
        raise ValueError("invalid proxy request") from exc
    if not _METHOD.fullmatch(method) or version not in {"HTTP/1.0", "HTTP/1.1"}:
        raise ValueError("invalid proxy request")
    if method == "CONNECT":
        parsed = _authority(target)
        port = parsed.port or 443
        _require_port(port)
        host = parsed.hostname or ""
        return method, target, port, f"https://{_url_host(host)}:{port}/", None
    parsed = urlsplit(target)
    if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("only absolute public HTTP proxy requests are allowed")
    try:
        port = parsed.port or 80
    except ValueError as exc:
        raise ValueError("invalid target port") from exc
    _require_port(port)
    path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    return method, path, port, target, parsed


def _authority(target: str) -> SplitResult:
    if any(ch in target for ch in "/?#@"):
        raise ValueError("invalid CONNECT authority")
    parsed = urlsplit(f"//{target}")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("invalid CONNECT port") from exc
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("invalid CONNECT authority")
    return parsed


def _require_port(port: int) -> None:
    if port not in _ALLOWED_PORTS:
        raise ValueError("browser proxy port is not allowed")


def _forward_head(head: bytes, path: str, target: SplitResult | None) -> bytes:
    if target is None:
        raise ValueError("HTTP target metadata is missing")
    lines = head[:-4].decode("iso-8859-1").split("\r\n")
    method, _absolute, version = lines[0].split(" ")
    headers: list[tuple[str, str]] = []
    upgrade = False
    for line in lines[1:]:
        name, separator, value = line.partition(":")
        if not separator or not _HEADER_NAME.fullmatch(name):
            raise ValueError("invalid proxy header")
        if name.lower() in _DROP_HEADERS:
            continue
        clean_value = value.strip()
        if "\r" in clean_value or "\n" in clean_value:
            raise ValueError("invalid proxy header")
        if name.lower() == "upgrade":
            upgrade = True
        headers.append((name, clean_value))
    port = target.port or 80
    host = _url_host(target.hostname or "")
    authority = host if port == 80 else f"{host}:{port}"
    headers.append(("Host", authority))
    headers.append(("Connection", "Upgrade" if upgrade else "close"))
    rendered = [f"{method} {path} {version}", *(f"{name}: {value}" for name, value in headers)]
    encoded = ("\r\n".join(rendered) + "\r\n\r\n").encode("iso-8859-1")
    if len(encoded) > _MAX_HEADER_BYTES:
        raise ValueError("forwarded header too large")
    return encoded


def _url_host(host: str) -> str:
    return f"[{host}]" if ":" in host else host


async def _relay(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    upstream_reader: asyncio.StreamReader,
    upstream_writer: asyncio.StreamWriter,
) -> None:
    async def copy(source: asyncio.StreamReader, destination: asyncio.StreamWriter) -> None:
        total = 0
        while True:
            chunk = await asyncio.wait_for(source.read(64 * 1024), _IDLE_TIMEOUT)
            if not chunk:
                return
            total += len(chunk)
            if total > _MAX_STREAM_BYTES:
                raise ValueError("browser proxy stream is too large")
            destination.write(chunk)
            await asyncio.wait_for(destination.drain(), _IDLE_TIMEOUT)

    tasks = {
        asyncio.create_task(copy(client_reader, upstream_writer)),
        asyncio.create_task(copy(upstream_reader, client_writer)),
    }
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    completed = await asyncio.gather(*done, return_exceptions=True)
    for result in completed:
        if isinstance(result, BaseException):
            raise result


async def _send_refusal(writer: asyncio.StreamWriter, status: int, reason: bytes) -> None:
    if writer.is_closing():
        return
    body = reason + b"\n"
    writer.write(
        f"HTTP/1.1 {status} {reason.decode('ascii')}\r\n".encode("ascii")
        + b"Content-Type: text/plain\r\n"
        + f"Content-Length: {len(body)}\r\n".encode("ascii")
        + b"Connection: close\r\n\r\n"
        + body
    )
    try:
        await asyncio.wait_for(writer.drain(), _CONNECT_TIMEOUT)
    except (OSError, asyncio.TimeoutError):
        pass


def _network_policy(env: Mapping[str, str]) -> dict[str, Any]:
    allowed = tuple(
        item.strip().lower()
        for item in str(env.get("BOLTRIG_BROWSER_ALLOWED_DOMAINS") or "").split(",")
        if item.strip()
    )
    return {
        "air_gapped": str(env.get("BOLTRIG_BROWSER_AIR_GAPPED") or "").strip().lower()
        in {"1", "true", "yes", "on"},
        "allowed_domains": allowed,
    }
