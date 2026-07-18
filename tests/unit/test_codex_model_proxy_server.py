"""Tests for the per-cell loopback model proxy (Stage B, piece 1).

Drives the real ``127.0.0.1`` server (Starlette + uvicorn) with an
``httpx.MockTransport`` upstream, pinning the security-critical behaviour from
ruling [2026] VJS-CC-VJS 1: the presented bearer is verified before anything is
forwarded, the cell's bearer is dropped and the kernel-only key injected upstream,
and every failure fails closed without leaking the key.
"""

from __future__ import annotations

from typing import Any

import httpx

from boltrig.fleet.infrastructure.codex_model_proxy_server import (
    PerCellModelProxyServer,
    _bearer,
)


async def _stream_body() -> Any:
    # A genuinely streaming upstream body, so the proxy's aiter_raw pass-through
    # is exercised the way a real gateway (SSE) would drive it.
    yield b'{"object":"response",'
    yield b'"output":[]}'


def _upstream(captured: dict[str, Any], *, fail: bool = False) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if fail:
            raise httpx.ConnectError("upstream down")
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = request.content
        return httpx.Response(
            200, headers={"content-type": "application/json"}, content=_stream_body()
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _server(verify: Any, client: httpx.AsyncClient) -> PerCellModelProxyServer:
    return PerCellModelProxyServer(
        verify_bearer=verify,
        upstream_base_url="http://gateway/v1",
        upstream_key="KERNEL-ONLY-KEY",
        client=client,
    )


async def test_valid_bearer_forwards_with_the_kernel_key_injected() -> None:
    captured: dict[str, Any] = {}

    async def verify(token: str) -> bool:
        return token == "good-bearer"

    server = _server(verify, _upstream(captured))
    port = await server.start()
    try:
        async with httpx.AsyncClient() as caller:
            resp = await caller.post(
                f"http://127.0.0.1:{port}/v1/responses",
                headers={"authorization": "Bearer good-bearer"},
                content=b'{"input":"hi"}',
            )
        assert resp.status_code == 200
        assert captured["url"] == "http://gateway/v1/responses"
        # the cell's bearer is dropped; the kernel-only key is injected upstream
        assert captured["auth"] == "Bearer KERNEL-ONLY-KEY"
        assert captured["body"] == b'{"input":"hi"}'
    finally:
        await server.aclose()


async def test_missing_bearer_is_rejected_before_any_upstream_call() -> None:
    captured: dict[str, Any] = {}

    async def verify(token: str) -> bool:
        return True  # would pass, but no bearer is presented

    server = _server(verify, _upstream(captured))
    port = await server.start()
    try:
        async with httpx.AsyncClient() as caller:
            resp = await caller.post(f"http://127.0.0.1:{port}/v1/responses", content=b"{}")
        assert resp.status_code == 401
        assert "url" not in captured  # never reached upstream
    finally:
        await server.aclose()


async def test_unverified_bearer_is_rejected() -> None:
    captured: dict[str, Any] = {}

    async def verify(token: str) -> bool:
        return False

    server = _server(verify, _upstream(captured))
    port = await server.start()
    try:
        async with httpx.AsyncClient() as caller:
            resp = await caller.post(
                f"http://127.0.0.1:{port}/v1/responses",
                headers={"authorization": "Bearer nope"},
                content=b"{}",
            )
        assert resp.status_code == 401
        assert "url" not in captured
    finally:
        await server.aclose()


async def test_verifier_error_fails_closed() -> None:
    async def verify(token: str) -> bool:
        raise RuntimeError("verifier exploded")

    server = _server(verify, _upstream({}))
    port = await server.start()
    try:
        async with httpx.AsyncClient() as caller:
            resp = await caller.post(
                f"http://127.0.0.1:{port}/v1/responses",
                headers={"authorization": "Bearer x"},
                content=b"{}",
            )
        assert resp.status_code == 401
    finally:
        await server.aclose()


async def test_upstream_failure_is_a_bounded_502() -> None:
    async def verify(token: str) -> bool:
        return True

    server = _server(verify, _upstream({}, fail=True))
    port = await server.start()
    try:
        async with httpx.AsyncClient() as caller:
            resp = await caller.post(
                f"http://127.0.0.1:{port}/v1/responses",
                headers={"authorization": "Bearer good"},
                content=b"{}",
            )
        assert resp.status_code == 502
        assert "KERNEL-ONLY-KEY" not in resp.text
    finally:
        await server.aclose()


def test_bearer_parsing() -> None:
    assert _bearer("Bearer abc") == "abc"
    assert _bearer("bearer abc") == "abc"
    assert _bearer("Basic abc") is None
    assert _bearer(None) is None
    assert _bearer("Bearer    ") is None
