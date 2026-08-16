from __future__ import annotations

import asyncio

import pytest

from boltrig.fleet import browser_egress_proxy


@pytest.mark.invariant("SEC-BRW-01")
async def test_browser_proxy_pins_vetted_public_http_and_scrubs_proxy_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[bytes] = []

    async def upstream(reader, writer) -> None:
        received.append(await reader.readuntil(b"\r\n\r\n"))
        body = b"public page"
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            + f"Content-Length: {len(body)}\r\n".encode("ascii")
            + b"Connection: close\r\n\r\n"
            + body
        )
        await writer.drain()
        writer.close()

    upstream_server = await asyncio.start_server(upstream, "127.0.0.1", 0)
    upstream_port = upstream_server.sockets[0].getsockname()[1]
    monkeypatch.setattr(browser_egress_proxy, "_ALLOWED_PORTS", frozenset({upstream_port}))

    def vetted(url: str, policy: dict):
        assert url == f"http://public.example:{upstream_port}/hello?x=1"
        assert policy == {"air_gapped": False, "allowed_domains": ()}
        return "public.example", "127.0.0.1"

    monkeypatch.setattr(browser_egress_proxy, "resolve_and_vet", vetted)
    proxy = await browser_egress_proxy.start_browser_egress_proxy(port=0, env={})
    proxy_port = proxy.sockets[0].getsockname()[1]
    async with upstream_server, proxy:
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
        writer.write(
            f"GET http://public.example:{upstream_port}/hello?x=1 HTTP/1.1\r\n".encode()
            + b"Host: attacker.invalid\r\n"
            + b"Proxy-Authorization: secret\r\n\r\n"
        )
        await writer.drain()
        response = await reader.read()
        writer.close()
        await writer.wait_closed()

    assert b"public page" in response
    assert received[0].startswith(b"GET /hello?x=1 HTTP/1.1\r\n")
    assert f"Host: public.example:{upstream_port}\r\n".encode() in received[0]
    assert b"attacker.invalid" not in received[0]
    assert b"Proxy-Authorization" not in received[0]


@pytest.mark.invariant("SEC-BRW-01")
async def test_browser_proxy_refuses_private_destinations_before_connecting() -> None:
    proxy = await browser_egress_proxy.start_browser_egress_proxy(port=0, env={})
    proxy_port = proxy.sockets[0].getsockname()[1]
    async with proxy:
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
        writer.write(b"GET http://127.0.0.1/private HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        await writer.drain()
        response = await reader.read()
        writer.close()
        await writer.wait_closed()

    assert response.startswith(b"HTTP/1.1 403 Forbidden")


@pytest.mark.invariant("SEC-BRW-01")
async def test_browser_proxy_pins_https_connect_tunnel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def upstream(reader, writer) -> None:
        assert await reader.readexactly(4) == b"PING"
        writer.write(b"PONG")
        await writer.drain()
        writer.close()

    upstream_server = await asyncio.start_server(upstream, "127.0.0.1", 0)
    upstream_port = upstream_server.sockets[0].getsockname()[1]
    monkeypatch.setattr(browser_egress_proxy, "_ALLOWED_PORTS", frozenset({upstream_port}))
    monkeypatch.setattr(
        browser_egress_proxy,
        "resolve_and_vet",
        lambda _url, _policy: ("public.example", "127.0.0.1"),
    )
    proxy = await browser_egress_proxy.start_browser_egress_proxy(port=0, env={})
    proxy_port = proxy.sockets[0].getsockname()[1]
    async with upstream_server, proxy:
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
        writer.write(
            f"CONNECT public.example:{upstream_port} HTTP/1.1\r\n"
            "Host: public.example\r\n\r\n".encode()
        )
        await writer.drain()
        assert b" 200 " in await reader.readuntil(b"\r\n\r\n")
        writer.write(b"PING")
        await writer.drain()
        assert await reader.readexactly(4) == b"PONG"
        writer.close()
        await writer.wait_closed()


@pytest.mark.invariant("SEC-BRW-01")
async def test_browser_proxy_bounds_page_authored_connection_fanout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = asyncio.Event()

    async def upstream(reader, writer) -> None:
        await release.wait()
        writer.close()

    upstream_server = await asyncio.start_server(upstream, "127.0.0.1", 0)
    upstream_port = upstream_server.sockets[0].getsockname()[1]
    monkeypatch.setattr(browser_egress_proxy, "_ALLOWED_PORTS", frozenset({upstream_port}))
    monkeypatch.setattr(browser_egress_proxy, "_MAX_CONCURRENT_CONNECTIONS", 1)
    monkeypatch.setattr(
        browser_egress_proxy,
        "resolve_and_vet",
        lambda _url, _policy: ("public.example", "127.0.0.1"),
    )
    proxy = await browser_egress_proxy.start_browser_egress_proxy(port=0, env={})
    proxy_port = proxy.sockets[0].getsockname()[1]
    async with upstream_server, proxy:
        first_reader, first_writer = await asyncio.open_connection("127.0.0.1", proxy_port)
        try:
            first_writer.write(
                f"CONNECT public.example:{upstream_port} HTTP/1.1\r\n"
                "Host: public.example\r\n\r\n".encode()
            )
            await first_writer.drain()
            first_head = await asyncio.wait_for(
                first_reader.readuntil(b"\r\n\r\n"), timeout=2.0
            )
            assert b" 200 " in first_head

            second_reader, second_writer = await asyncio.open_connection(
                "127.0.0.1", proxy_port
            )
            try:
                second_writer.write(
                    f"CONNECT public.example:{upstream_port} HTTP/1.1\r\n"
                    "Host: public.example\r\n\r\n".encode()
                )
                await second_writer.drain()
                refused = await asyncio.wait_for(
                    second_reader.readuntil(b"\r\n\r\n"), timeout=2.0
                )
                assert refused.startswith(b"HTTP/1.1 503 Service Unavailable")
            finally:
                second_writer.close()
                await second_writer.wait_closed()
        finally:
            release.set()
            first_writer.close()
            await first_writer.wait_closed()
