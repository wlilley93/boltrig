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
import pytest

from boltrig.fleet.infrastructure.model_proxy_tool_ceiling import (
    MAX_MODEL_CALL_BODY_BYTES,
)
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
        captured["virtual_key"] = request.headers.get("x-bf-vk")
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
        allowed_model="gpt-5.2-codex",
    )


@pytest.mark.invariant("SEC-AIKEY-01")
async def test_scoped_virtual_key_is_injected_without_forwarding_the_cell_bearer() -> None:
    captured: dict[str, Any] = {}

    async def verify(token: str) -> bool:
        return token == "cell-bearer"

    server = PerCellModelProxyServer(
        verify_bearer=verify,
        upstream_base_url="http://gateway/v1",
        upstream_key="KERNEL-ONLY-KEY",
        upstream_virtual_key="vk-scoped-only",
        client=_upstream(captured),
        allowed_model="gpt-5.2-codex",
    )
    port = await server.start()
    try:
        async with httpx.AsyncClient() as caller:
            response = await caller.post(
                f"http://127.0.0.1:{port}/v1/responses",
                headers={"authorization": "Bearer cell-bearer"},
                content=b'{"model":"gpt-5.2-codex","input":"hi"}',
            )
        assert response.status_code == 200
        assert captured["auth"] == "Bearer KERNEL-ONLY-KEY"
        assert captured["virtual_key"] == "vk-scoped-only"
        assert "cell-bearer" not in repr(captured)
    finally:
        await server.aclose()


async def test_the_tool_ceiling_is_enforced_before_the_call_leaves_the_box() -> None:
    """Codex offers exec_command on every turn; the read-only lane must never see it.

    config.toml cannot suppress Codex's built-in tools, so this proxy is the only
    place the admission-time "no effective tools" assertion can be made true.
    """

    captured: dict[str, Any] = {}

    async def verify(token: str) -> bool:
        return True

    server = _server(verify, _upstream(captured))
    port = await server.start()
    try:
        async with httpx.AsyncClient() as caller:
            resp = await caller.post(
                f"http://127.0.0.1:{port}/v1/responses",
                headers={"authorization": "Bearer good-bearer"},
                content=(
                    b'{"model":"gpt-5.2-codex","input":"hi",'
                    b'"tools":[{"type":"function","name":"exec_command"}]}'
                ),
            )
        assert resp.status_code == 200
        assert b"exec_command" not in captured["body"]
        assert b'"tools"' not in captured["body"]
    finally:
        await server.aclose()


async def test_a_native_child_cannot_select_another_model() -> None:
    captured: dict[str, Any] = {}

    async def verify(token: str) -> bool:
        return True

    server = _server(verify, _upstream(captured))
    port = await server.start()
    try:
        async with httpx.AsyncClient() as caller:
            response = await caller.post(
                f"http://127.0.0.1:{port}/v1/responses",
                headers={"authorization": "Bearer good-bearer"},
                content=b'{"model":"other-provider/model","input":"hi"}',
            )
        assert response.status_code == 400
        assert response.json() == {"error": "model_ceiling"}
        assert "url" not in captured
    finally:
        await server.aclose()


async def test_root_and_native_child_requests_must_carry_the_pinned_effort() -> None:
    captured: dict[str, Any] = {}

    async def verify(token: str) -> bool:
        return True

    server = PerCellModelProxyServer(
        verify_bearer=verify,
        upstream_base_url="http://gateway/v1",
        upstream_key="KERNEL-ONLY-KEY",
        client=_upstream(captured),
        allowed_model="gpt-5.2-codex",
        allowed_reasoning_effort="high",
    )
    port = await server.start()
    try:
        async with httpx.AsyncClient() as caller:
            for body in (
                b'{"model":"gpt-5.2-codex","input":"hi"}',
                (
                    b'{"model":"gpt-5.2-codex","input":"hi",'
                    b'"reasoning":{"effort":"medium"}}'
                ),
            ):
                response = await caller.post(
                    f"http://127.0.0.1:{port}/v1/responses",
                    headers={"authorization": "Bearer good-bearer"},
                    content=body,
                )
                assert response.status_code == 400
                assert response.json() == {"error": "reasoning_effort_ceiling"}
                assert "url" not in captured

            accepted = await caller.post(
                f"http://127.0.0.1:{port}/v1/responses",
                headers={"authorization": "Bearer good-bearer"},
                content=(
                    b'{"model":"gpt-5.2-codex","input":"hi",'
                    b'"reasoning":{"effort":"high","summary":"auto"}}'
                ),
            )
        assert accepted.status_code == 200
        assert b'"effort":"high"' in captured["body"]
    finally:
        await server.aclose()


async def test_every_unverifiable_body_shape_is_refused_without_reaching_upstream() -> None:
    """F6 FAIL-CLOSED as a gate: a tool set we cannot read is one we cannot bound."""

    async def verify(token: str) -> bool:
        return True

    bodies = [
        b"{not json",  # unparseable
        b"\xff\xfe",  # not utf-8
        b'{"tools":"exec_command"}',  # tools present but not a list
        b"x" * (MAX_MODEL_CALL_BODY_BYTES + 1),  # beyond the verifiable cap
    ]
    for body in bodies:
        captured: dict[str, Any] = {}
        server = _server(verify, _upstream(captured))
        port = await server.start()
        try:
            async with httpx.AsyncClient() as caller:
                resp = await caller.post(
                    f"http://127.0.0.1:{port}/v1/responses",
                    headers={"authorization": "Bearer good-bearer"},
                    content=body,
                )
            assert resp.status_code == 400
            assert "url" not in captured  # nothing was built or sent upstream
        finally:
            await server.aclose()


async def test_an_unverifiable_body_is_refused_without_reaching_upstream() -> None:
    captured: dict[str, Any] = {}

    async def verify(token: str) -> bool:
        return True

    server = _server(verify, _upstream(captured))
    port = await server.start()
    try:
        async with httpx.AsyncClient() as caller:
            resp = await caller.post(
                f"http://127.0.0.1:{port}/v1/responses",
                headers={"authorization": "Bearer good-bearer"},
                content=b"{not json",
            )
        assert resp.status_code == 400
        assert "url" not in captured
    finally:
        await server.aclose()


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
                content=b'{"model":"gpt-5.2-codex","input":"hi"}',
            )
        assert resp.status_code == 200
        assert captured["url"] == "http://gateway/v1/responses"
        # the cell's bearer is dropped; the kernel-only key is injected upstream
        assert captured["auth"] == "Bearer KERNEL-ONLY-KEY"
        assert captured["body"] == b'{"model":"gpt-5.2-codex","input":"hi"}'
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
                content=b'{"model":"gpt-5.2-codex"}',
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
                content=b'{"model":"gpt-5.2-codex"}',
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
                content=b'{"model":"gpt-5.2-codex"}',
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


async def test_store_bearer_verifier_accepts_an_issued_bearer_and_rejects_others() -> None:
    from boltrig.fleet.application.model_proxy_grants import (
        PhaseScopedModelProxyGrantBroker,
    )
    from boltrig.fleet.infrastructure.codex_model_proxy_server import store_bearer_verifier
    from boltrig.fleet.infrastructure.memory_model_proxy_grants import (
        MemoryModelProxyGrantStore,
    )
    from tests.unit.test_model_proxy_grants import _binding

    store = MemoryModelProxyGrantStore()
    broker = PhaseScopedModelProxyGrantBroker(store)
    binding = _binding()
    issued = await broker.issue("startup-req-1", binding, ttl_seconds=60, generation=1)
    bearer = issued.bearer.reveal()

    verify = store_bearer_verifier(store, generation=1)
    assert await verify(bearer) is True  # the issued bearer is accepted
    assert await verify("not-a-real-bearer") is False  # an unknown bearer is rejected
    assert await verify("") is False

    # bound to the rollout generation: the same bearer fails at another generation
    verify_other_gen = store_bearer_verifier(store, generation=2)
    assert await verify_other_gen(bearer) is False


async def test_an_unsolicited_tool_call_in_the_response_is_truncated_not_relayed() -> None:
    """Exclusivity limb (c): the gateway must not confer a tool we never offered.

    Stripping tools from the request bounds what the model is OFFERED. A gateway
    returning a function_call anyway would still be executed by the App Server, so
    the relay stops. Status and headers are already gone by then, which is why
    truncation rather than an error status is the fail-closed outcome.
    """

    async def verify(token: str) -> bool:
        return True

    async def hostile_body() -> Any:
        yield b'data: {"type":"response.output_text.delta","delta":"ok"}\n\n'
        yield (
            b'data: {"type":"response.output_item.added","item":'
            b'{"type":"function_call","name":"exec_command"}}\n\n'
        )
        yield b'data: {"type":"response.completed"}\n\n'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=hostile_body()
        )

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    server = _server(verify, upstream)
    port = await server.start()
    try:
        async with httpx.AsyncClient() as caller:
            resp = await caller.post(
                f"http://127.0.0.1:{port}/v1/responses",
                headers={"authorization": "Bearer good-bearer"},
                content=b'{"model":"gpt-5.2-codex","input":"hi"}',
            )
        assert b"exec_command" not in resp.content
        assert b"function_call" not in resp.content
        assert b'"delta":"ok"' in resp.content  # the safe prefix still relayed
        assert b"response.completed" not in resp.content  # relay stopped
    finally:
        await server.aclose()


async def test_a_traversing_path_cannot_escape_the_v1_base() -> None:
    """Exclusivity limb (a): the chokepoint is only the only path if it holds.

    httpx normalizes "/v1/../admin" to "/admin", so without a guard a cell could
    reach any gateway endpoint with the kernel-only key attached. The composed URL
    is checked rather than the raw tail, because that is what would be sent.
    """

    async def verify(token: str) -> bool:
        return True

    for tail in ("../admin", "../../etc/passwd", "a/../../admin"):
        captured: dict[str, Any] = {}
        server = _server(verify, _upstream(captured))
        port = await server.start()
        try:
            async with httpx.AsyncClient() as caller:
                resp = await caller.request(
                    "POST",
                    f"http://127.0.0.1:{port}/v1/{tail}",
                    headers={"authorization": "Bearer good-bearer"},
                    content=b'{"model":"gpt-5.2-codex"}',
                    extensions={"target": f"/v1/{tail}".encode()},
                )
            assert resp.status_code == 400, tail
            assert "url" not in captured, tail  # nothing reached upstream
        finally:
            await server.aclose()
