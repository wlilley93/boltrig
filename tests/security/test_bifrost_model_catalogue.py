"""Bifrost discovery is internal, bounded, author-only, and content-safe."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from boltrig.fleet import bifrost_model_catalogue as catalogue_module
from boltrig.fleet.bifrost_model_catalogue import (
    MAX_BIFROST_CATALOGUE_BODY_BYTES,
    BifrostModelCatalogue,
)
from boltrig.kernel import Kernel
from boltrig.kernel.app import Principal, create_app
from boltrig.store import InMemoryStore

_BASE_ENV = {"BOLTRIG_MODEL_GATEWAY_URL": "http://bifrost:8080/v1"}
_BIFROST_V162_INDEX_DIGEST = (
    "sha256:c4de3a1d6bd2f9b8b0b8f508deaaf0337a793603d2b84b61138cdb35f94a4318"
)


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


def _assert_unavailable(result: object, reason: str) -> None:
    assert result == {"status": "unavailable", "models": [], "reason": reason}


@pytest.mark.security
@pytest.mark.invariant("FR-GW-05")
async def test_catalogue_cache_singleflights_and_expires_fail_closed() -> None:
    now = [10.0]
    calls = 0

    async def fetch(*_args: object) -> tuple[int, bytes]:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        if calls == 1:
            return 200, _json_bytes(
                {
                    "data": [
                        {"id": "provider/model-a", "architecture": {"input_modalities": ["text"]}}
                    ]
                }
            )
        raise httpx.ConnectError("offline")

    catalogue = BifrostModelCatalogue(
        env=_BASE_ENV,
        page_fetcher=fetch,
        cache_ttl_seconds=5,
        clock=lambda: now[0],
    )
    first = await asyncio.gather(*(catalogue.list_models() for _ in range(8)))
    assert calls == 1
    assert all(result == first[0] for result in first)
    first[0]["models"][0]["id"] = "caller-mutated"
    cached = await catalogue.list_models()
    assert cached["models"][0]["id"] == "provider/model-a"
    assert calls == 1

    now[0] = 16.0
    expired = await asyncio.gather(*(catalogue.list_models() for _ in range(8)))
    assert calls == 2
    assert all(
        result == {"status": "unavailable", "models": [], "reason": "gateway_unavailable"}
        for result in expired
    )


@pytest.mark.security
@pytest.mark.invariant("FR-GW-05")
async def test_catalogue_slow_body_cannot_extend_the_wall_clock_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def drip(*_args: object) -> tuple[int, bytes]:
        started.set()
        try:
            while True:
                await asyncio.sleep(0.01)
        finally:
            cancelled.set()

    monkeypatch.setattr(catalogue_module, "BIFROST_CATALOGUE_TIMEOUT_SECONDS", 0.03)
    result = await BifrostModelCatalogue(
        env=_BASE_ENV,
        page_fetcher=drip,
        cache_ttl_seconds=0,
    ).list_models()

    assert started.is_set() and cancelled.is_set()
    assert result == {
        "status": "unavailable",
        "models": [],
        "reason": "gateway_timeout",
    }


def _client(catalogue: object) -> TestClient:
    async def resolver(request: Request) -> Principal:
        bearer = request.headers.get("authorization")
        if bearer == "Bearer author-session":
            return Principal(tenant_id="acme", subject="alice", role="org-admin")
        if bearer == "Bearer member-session":
            return Principal(tenant_id="acme", subject="bob", role="member")
        raise HTTPException(status_code=401, detail="invalid session")

    return TestClient(
        create_app(
            Kernel(InMemoryStore()),
            principal_resolver=resolver,
            platform={"bifrost_models": catalogue},
        )
    )


@pytest.mark.security
@pytest.mark.invariant("FR-GW-05")
def test_bifrost_model_catalogue_contract_tracks_pinned_v162_digest() -> None:
    """Keep fixtures coupled to the exact upstream contract they model.

    Docker registry inspection maps this immutable index digest to
    ``maximhq/bifrost:v1.6.2``. Its ``transports/v1.6.2`` tag resolves to commit
    ``1ca45ea799289f6c63308360030da3bae4b67064``; that handler consumes
    ``page_size``/``page_token`` and emits ``data``/``next_page_token``.
    """

    compose = (Path(__file__).parents[2] / "docker-compose.yml").read_text(encoding="utf-8")
    assert f"image: maximhq/bifrost@{_BIFROST_V162_INDEX_DIGEST}" in compose


@pytest.mark.security
@pytest.mark.invariant("FR-GW-05")
def test_bifrost_model_catalogue_route_is_author_only_and_redacts_upstream() -> None:
    calls: list[dict[str, object]] = []
    gateway_key = "kernel-only-secret"

    async def fetch(
        url: str,
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_body_bytes: int,
    ) -> tuple[int, bytes]:
        calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "timeout": timeout_seconds,
                "max_body": max_body_bytes,
            }
        )
        return 200, _json_bytes(
            {
                "data": [
                    {
                        "name": "openai/gpt-5.4",
                        "architecture": {
                            "input_modalities": ["text", "image"],
                            "output_modalities": ["text"],
                        },
                        "provider": "openai",
                        "accessible_by_keys": ["upstream-key-record"],
                    },
                    {
                        "id": "anthropic/claude-sonnet-4-6",
                        "owned_by": "anthropic",
                        "base_url": "https://provider.invalid/v1",
                    },
                ],
                "gateway_url": "http://bifrost:8080/v1",
            }
        )

    catalogue = BifrostModelCatalogue(
        env={**_BASE_ENV, "BOLTRIG_MODEL_GATEWAY_KEY": gateway_key},
        page_fetcher=fetch,
    )
    client = _client(catalogue)

    assert client.get("/v1/bifrost/models").status_code == 401
    assert (
        client.get(
            "/v1/bifrost/models",
            headers={"authorization": "Bearer member-session"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/v1/bifrost/models",
            headers={"authorization": "Bearer author-session"},
        ).status_code
        == 405
    )
    assert calls == []

    response = client.get(
        "/v1/bifrost/models",
        headers={"authorization": "Bearer author-session"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "models": [
            {
                "id": "openai/gpt-5.4",
                "name": "openai/gpt-5.4",
                "input_modalities": ["text", "image"],
            },
            {
                "id": "anthropic/claude-sonnet-4-6",
                "name": "anthropic/claude-sonnet-4-6",
            },
        ],
        "reason": None,
    }
    assert calls == [
        {
            "url": "http://bifrost:8080/v1/models?page_size=100",
            "headers": {
                "accept": "application/json",
                "authorization": f"Bearer {gateway_key}",
            },
            "timeout": catalogue_module.BIFROST_CATALOGUE_TIMEOUT_SECONDS,
            "max_body": MAX_BIFROST_CATALOGUE_BODY_BYTES,
        }
    ]
    public_text = response.text.lower()
    for private_value in (
        gateway_key,
        "http://bifrost",
        "provider",
        "accessible_by_keys",
        "upstream-key-record",
        "owned_by",
        "base_url",
    ):
        assert private_value.lower() not in public_text


@pytest.mark.security
@pytest.mark.invariant("FR-GW-05")
def test_bifrost_model_catalogue_route_reprojects_an_injected_provider() -> None:
    class UnsafeProvider:
        async def list_models(self) -> dict[str, object]:
            return {
                "status": "ok",
                "models": [
                    {
                        "id": "openai/gpt-5.4",
                        "name": "GPT 5.4",
                        "input_modalities": ["text"],
                        "provider": "openai",
                        "api_key": "provider-secret",
                    }
                ],
                "reason": None,
                "gateway_url": "http://bifrost:8080/v1",
            }

    response = _client(UnsafeProvider()).get(
        "/v1/bifrost/models",
        headers={"authorization": "Bearer author-session"},
    )
    assert response.json() == {
        "status": "ok",
        "models": [
            {
                "id": "openai/gpt-5.4",
                "name": "GPT 5.4",
                "input_modalities": ["text"],
            }
        ],
        "reason": None,
    }
    assert "provider-secret" not in response.text
    assert "http://bifrost" not in response.text


@pytest.mark.security
@pytest.mark.invariant("FR-GW-05")
@pytest.mark.parametrize(
    "gateway_url",
    [
        "https://gateway.example.com/v1",
        "http://169.254.169.254/v1",
        "http://bifrost.example/v1",
        "file:///v1",
        "http://user:password@bifrost:8080/v1",
        "http://bifrost:8080/v1?target=metadata",
        "http://bifrost:8080/v1#fragment",
        "http://bifrost:8080/api/v1",
        " http://bifrost:8080/v1",
        "http://bifrost:99999/v1",
    ],
)
async def test_bifrost_model_catalogue_rejects_ssrf_and_malformed_gateway_urls(
    gateway_url: str,
) -> None:
    async def must_not_fetch(*_args: object) -> tuple[int, bytes]:
        raise AssertionError("an invalid gateway URL reached the network seam")

    result = await BifrostModelCatalogue(
        env={"BOLTRIG_MODEL_GATEWAY_URL": gateway_url},
        page_fetcher=must_not_fetch,
    ).list_models()
    _assert_unavailable(result, "invalid_gateway_configuration")


@pytest.mark.security
@pytest.mark.invariant("FR-GW-05")
async def test_bifrost_model_catalogue_rejects_redirect_timeout_and_bad_transport_results() -> None:
    async def redirected(*_args: object) -> tuple[int, bytes]:
        return 307, b""

    async def timed_out(*_args: object) -> tuple[int, bytes]:
        raise httpx.ReadTimeout("secret-bearing upstream timeout")

    async def bad_status(*_args: object) -> Any:
        return "200", b'{"data":[]}'

    async def failed(*_args: object) -> tuple[int, bytes]:
        raise httpx.ConnectError("http://bifrost:8080/v1?key=secret")

    for fetcher, reason in (
        (redirected, "gateway_redirect_rejected"),
        (timed_out, "gateway_timeout"),
        (bad_status, "gateway_response_rejected"),
        (failed, "gateway_unavailable"),
    ):
        result = await BifrostModelCatalogue(
            env=_BASE_ENV,
            page_fetcher=fetcher,
        ).list_models()
        _assert_unavailable(result, reason)
        rendered = repr(result).lower()
        assert "secret" not in rendered
        assert "http://bifrost" not in rendered

    _assert_unavailable(
        await BifrostModelCatalogue(env={}, page_fetcher=redirected).list_models(),
        "not_configured",
    )


@pytest.mark.security
@pytest.mark.invariant("FR-GW-05")
async def test_bifrost_model_catalogue_bounds_body_rows_and_schema() -> None:
    async def result_for(body: bytes) -> object:
        async def fetch(*_args: object) -> tuple[int, bytes]:
            return 200, body

        return await BifrostModelCatalogue(
            env=_BASE_ENV,
            page_fetcher=fetch,
        ).list_models()

    _assert_unavailable(
        await result_for(b"x" * (MAX_BIFROST_CATALOGUE_BODY_BYTES + 1)),
        "response_too_large",
    )
    too_many = {"data": [{"id": f"model-{index}"} for index in range(501)]}
    _assert_unavailable(await result_for(_json_bytes(too_many)), "catalogue_too_large")

    malformed_payloads = (
        [],
        {"models": []},
        {"data": [{"provider": "openai"}]},
        {"data": [{"id": "model-a"}, {"id": "model-a"}]},
        {"data": [{"id": " model-a"}]},
        {
            "data": [
                {
                    "id": "model-a",
                    "architecture": {"input_modalities": ["text", "text"]},
                }
            ]
        },
        {"data": [{"id": "model-a"}], "next_page_token": True},
        {"data": [{"id": "model-a"}], "next_page_token": "bad+token="},
        {"data": [{"id": "model-a", "architecture": []}]},
    )
    for payload in malformed_payloads:
        _assert_unavailable(await result_for(_json_bytes(payload)), "schema_invalid")


@pytest.mark.security
@pytest.mark.invariant("FR-GW-05")
async def test_bifrost_model_catalogue_pagination_is_bounded_and_all_or_nothing() -> None:
    requested_tokens: list[str | None] = []

    async def paginated(url: str, *_args: object) -> tuple[int, bytes]:
        query = parse_qs(urlsplit(url).query)
        token = query.get("page_token", [None])[0]
        requested_tokens.append(token)
        offset = {None: 0, "cursor-100": 100, "cursor-200": 200}[token]
        count = min(100, 201 - offset)
        next_token = {0: "cursor-100", 100: "cursor-200", 200: None}[offset]
        payload = {"data": [{"id": f"model-{index}"} for index in range(offset, offset + count)]}
        if next_token is not None:
            payload["next_page_token"] = next_token
        return 200, _json_bytes(payload)

    result = await BifrostModelCatalogue(
        env=_BASE_ENV,
        page_fetcher=paginated,
    ).list_models()
    assert result["status"] == "ok"
    assert len(result["models"]) == 201
    assert requested_tokens == [None, "cursor-100", "cursor-200"]

    calls = 0

    async def endless(url: str, *_args: object) -> tuple[int, bytes]:
        nonlocal calls
        calls += 1
        assert parse_qs(urlsplit(url).query)["page_size"] == ["100"]
        return 200, _json_bytes(
            {
                "data": [{"id": f"item-{calls}"}],
                "next_page_token": f"cursor-{calls}",
            }
        )

    limited = await BifrostModelCatalogue(
        env=_BASE_ENV,
        page_fetcher=endless,
    ).list_models()
    _assert_unavailable(limited, "pagination_limit")
    assert calls == catalogue_module.MAX_BIFROST_CATALOGUE_PAGES

    page = 0

    async def invalid_second_page(*_args: object) -> tuple[int, bytes]:
        nonlocal page
        page += 1
        if page == 1:
            return 200, _json_bytes({"data": [{"id": "partial"}], "next_page_token": "cursor-1"})
        return 200, b'{"data":[{"provider":"private"}]}'

    partial = await BifrostModelCatalogue(
        env=_BASE_ENV,
        page_fetcher=invalid_second_page,
    ).list_models()
    _assert_unavailable(partial, "schema_invalid")
    assert "partial" not in repr(partial)


@pytest.mark.security
@pytest.mark.invariant("FR-GW-05")
async def test_bifrost_model_catalogue_transport_disables_redirects_and_environment_proxies(
    monkeypatch,
) -> None:
    seen: dict[str, object] = {}
    response_chunks = [b'{"data":[]}']

    class FakeResponse:
        status_code = 200
        headers: dict[str, str] = {}

        async def __aenter__(self) -> FakeResponse:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def aiter_raw(self):
            for chunk in response_chunks:
                yield chunk

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            seen["client"] = kwargs

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        def stream(self, method: str, url: str, **kwargs: object) -> FakeResponse:
            seen["request"] = {"method": method, "url": url, **kwargs}
            return FakeResponse()

    monkeypatch.setattr(catalogue_module.httpx, "AsyncClient", FakeClient)
    status, body = await catalogue_module._fetch_page(
        "https://localhost/v1/models",
        {"accept": "application/json", "authorization": "Bearer server-key"},
        0.4,
        1024,
    )
    assert (status, body) == (200, b'{"data":[]}')
    client_options = seen["client"]
    assert isinstance(client_options, dict)
    assert client_options["follow_redirects"] is False
    assert client_options["trust_env"] is False
    assert isinstance(client_options["timeout"], httpx.Timeout)
    request_options = seen["request"]
    assert isinstance(request_options, dict)
    assert request_options == {
        "method": "GET",
        "url": "https://localhost/v1/models",
        "headers": {
            "accept": "application/json",
            "accept-encoding": "identity",
            "authorization": "Bearer server-key",
        },
    }

    response_chunks[:] = [b"abc", b"def"]
    with pytest.raises(catalogue_module._ResponseTooLarge):
        await catalogue_module._fetch_page(
            "https://localhost/v1/models",
            {"accept": "application/json"},
            0.4,
            5,
        )

    class CompressedResponse(FakeResponse):
        headers = {"content-encoding": "gzip", "content-length": "32"}

        async def aiter_raw(self):
            raise AssertionError("encoded response must be rejected before body consumption")
            yield b""  # pragma: no cover - keeps this an async generator

    def compressed_stream(
        self: FakeClient, method: str, url: str, **kwargs: object
    ) -> CompressedResponse:
        return CompressedResponse()

    monkeypatch.setattr(FakeClient, "stream", compressed_stream)
    with pytest.raises(catalogue_module._ResponseEncodingRejected):
        await catalogue_module._fetch_page(
            "https://localhost/v1/models",
            {"accept": "application/json"},
            0.4,
            MAX_BIFROST_CATALOGUE_BODY_BYTES,
        )

    class CompressedClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> CompressedClient:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        def stream(self, *_args: object, **_kwargs: object) -> CompressedResponse:
            return CompressedResponse()

    monkeypatch.setattr(catalogue_module.httpx, "AsyncClient", CompressedClient)
    rejected = await BifrostModelCatalogue(env=_BASE_ENV, cache_ttl_seconds=0).list_models()
    _assert_unavailable(rejected, "gateway_response_rejected")

    async def empty_fetch(*_args: object) -> tuple[int, bytes]:
        return 200, b'{"data":[]}'

    assert await BifrostModelCatalogue(
        env={"BOLTRIG_MODEL_GATEWAY_URL": "https://localhost/v1"},
        page_fetcher=empty_fetch,
    ).list_models() == {"status": "ok", "models": [], "reason": None}
