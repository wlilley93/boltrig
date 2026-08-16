"""Scoped BYOK material is converted into one exact Bifrost virtual key."""

from __future__ import annotations

import json

import httpx
import pytest

from boltrig.identity import AiKeyResolution
from boltrig.identity.bifrost_user_binding import (
    BifrostUserBindingUnavailable,
    BifrostUserGateway,
)
from boltrig.identity.bifrost_user_transport import BifrostUserTransport
from boltrig.store import InMemoryStore
from boltrig.store.sealing import is_sealed


def _resolution(*, credential_ref: str = "staged:key-1") -> AiKeyResolution:
    return AiKeyResolution(
        level="user",
        scope_id="alice",
        modality="text",
        credential_ref=credential_ref,
        provider="openai",
        model="openai/gpt-5.4",
    )


class _Bifrost:
    def __init__(self, *, paginate: bool = False) -> None:
        self.requests: list[tuple[str, str, dict[str, object] | None, dict[str, str]]] = []
        self.providers: set[str] = set()
        self.provider_key_id = ""
        self.provider_key_model = ""
        self.virtual_key_row: dict[str, object] | None = None
        self.paginate = paginate

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        headers = {key.lower(): value for key, value in request.headers.items()}
        self.requests.append((request.method, str(request.url), body, headers))
        path = request.url.path
        if request.method == "GET" and path == "/api/providers":
            return httpx.Response(
                200,
                json={"providers": [{"name": item} for item in sorted(self.providers)]},
            )
        if request.method == "POST" and path == "/api/providers":
            assert body is not None
            self.providers.add(str(body["provider"]))
            return httpx.Response(201, json={})
        if request.method == "GET" and path.startswith("/api/providers/openai/keys/"):
            if not self.provider_key_id:
                return httpx.Response(404, json={})
            return httpx.Response(
                200,
                json={"id": self.provider_key_id, "models": [self.provider_key_model]},
            )
        if request.method in {"POST", "PUT"} and (
            path == "/api/providers/openai/keys" or path.startswith("/api/providers/openai/keys/")
        ):
            assert body is not None
            self.provider_key_id = str(body["id"])
            self.provider_key_model = str(body["models"][0])
            assert body["models"] == ["gpt-5.4"]
            assert body["value"]["from_env"] is False
            return httpx.Response(201, json={})
        if request.method == "GET" and path == "/api/governance/virtual-keys":
            return httpx.Response(
                200,
                json={"virtual_keys": [self.virtual_key_row] if self.virtual_key_row else []},
            )
        if request.method == "POST" and path == "/api/governance/virtual-keys":
            assert body is not None
            config = body["provider_configs"][0]
            assert config == {
                "provider": "openai",
                "weight": 1,
                "allowed_models": ["gpt-5.4"],
                "blacklisted_models": [],
                "key_ids": [self.provider_key_id],
            }
            self.virtual_key_row = {
                "id": "vk-id-1",
                "name": body["name"],
                "value": "vk-scoped-secret",
                "is_active": True,
                "provider_configs": [config],
            }
            return httpx.Response(201, json={"virtual_key": self.virtual_key_row})
        if request.method == "DELETE" and path == "/api/governance/virtual-keys/vk-id-1":
            self.virtual_key_row = None
            return httpx.Response(204)
        if request.method == "DELETE" and path.startswith("/api/providers/openai/keys/"):
            self.provider_key_id = ""
            self.provider_key_model = ""
            return httpx.Response(204)
        if request.method == "GET" and path == "/v1/models":
            assert request.url.params.get("provider") == "openai"
            assert headers.get("x-bf-vk") == "vk-scoped-secret"
            if self.paginate and not request.url.params.get("page_token"):
                return httpx.Response(
                    200,
                    json={
                        "data": [{"id": "openai/a-different-model"}],
                        "next_page_token": "next page",
                    },
                )
            return httpx.Response(200, json={"data": [{"id": "openai/gpt-5.4"}]})
        raise AssertionError(f"unexpected Bifrost request: {request.method} {request.url}")


@pytest.mark.security
@pytest.mark.invariant("FR-AIKEY-03")
async def test_scoped_key_provisions_exact_virtual_key_and_seals_it() -> None:
    upstream = _Bifrost(paginate=True)
    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    store = InMemoryStore()
    gateway = BifrostUserGateway(
        env={"BOLTRIG_MODEL_GATEWAY_URL": "http://bifrost:8080/v1"},
        client=client,
    )

    binding = await gateway.ensure(store, "tenant-a", _resolution(), "provider-secret")

    assert binding.model_id == "openai/gpt-5.4"
    assert repr(binding) == "BifrostUserBinding(redacted=True)"
    assert "provider-secret" not in repr(binding)
    assert "vk-scoped-secret" not in repr(binding)
    stored = await store.get_credential_ref("tenant-a", binding.credential_ref)
    assert stored["secret"] == "vk-scoped-secret"
    raw = store._creds[("tenant-a", binding.credential_ref)]
    assert is_sealed(raw)
    assert "provider-secret" not in json.dumps(raw)
    assert "vk-scoped-secret" not in json.dumps(raw)
    assert any(
        "page_token=next%20page" in url for _method, url, _body, _headers in upstream.requests
    )

    writes_before = sum(method == "POST" for method, *_rest in upstream.requests)
    same = await gateway.ensure(store, "tenant-a", _resolution(), "provider-secret")
    assert same == binding
    assert sum(method == "POST" for method, *_rest in upstream.requests) == writes_before
    await client.aclose()


@pytest.mark.security
@pytest.mark.invariant("SEC-AIKEY-01")
async def test_replacement_rotates_the_stable_scope_in_place_and_revoke_cleans_it() -> None:
    upstream = _Bifrost()
    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    store = InMemoryStore()
    gateway = BifrostUserGateway(
        env={"BOLTRIG_MODEL_GATEWAY_URL": "http://bifrost:8080/v1"},
        client=client,
    )
    old = _resolution(credential_ref="staged:old")
    replacement = _resolution(credential_ref="staged:new")

    first = await gateway.ensure(store, "tenant-a", old, "provider-secret-old")
    second = await gateway.ensure(store, "tenant-a", replacement, "provider-secret-new")

    assert first.credential_ref == second.credential_ref
    assert first.provider_key_id == second.provider_key_id
    assert first.virtual_key_id == second.virtual_key_id
    puts = [body for method, _url, body, _headers in upstream.requests if method == "PUT"]
    assert puts[-1]["value"] == {
        "value": "provider-secret-new",
        "from_env": False,
    }
    stored = await store.get_credential_ref("tenant-a", second.credential_ref)
    assert stored["source_credential_ref"] == "staged:new"

    await gateway.revoke(store, "tenant-a", replacement)

    assert await store.get_credential_ref("tenant-a", second.credential_ref) is None
    assert upstream.provider_key_id == ""
    assert upstream.virtual_key_row is None
    await client.aclose()


@pytest.mark.security
@pytest.mark.invariant("SEC-AIKEY-01")
async def test_binding_ids_are_tenant_and_credential_scoped() -> None:
    store = InMemoryStore()
    first_upstream = _Bifrost()
    second_upstream = _Bifrost()
    first_client = httpx.AsyncClient(transport=httpx.MockTransport(first_upstream))
    second_client = httpx.AsyncClient(transport=httpx.MockTransport(second_upstream))
    first = await BifrostUserGateway(
        env={"BOLTRIG_MODEL_GATEWAY_URL": "http://bifrost:8080/v1"},
        client=first_client,
    ).ensure(store, "tenant-a", _resolution(), "provider-secret")
    second = await BifrostUserGateway(
        env={"BOLTRIG_MODEL_GATEWAY_URL": "http://bifrost:8080/v1"},
        client=second_client,
    ).ensure(store, "tenant-b", _resolution(), "provider-secret")

    assert first.credential_ref != second.credential_ref
    assert first.provider_key_id != second.provider_key_id
    await first_client.aclose()
    await second_client.aclose()


@pytest.mark.security
@pytest.mark.parametrize(
    "gateway_url",
    [
        "https://example.com/v1",
        "http://user:pass@bifrost:8080/v1",
        "http://bifrost:8080/v1?redirect=https://example.com",
        "http://bifrost:8080/admin",
    ],
)
def test_gateway_admin_target_is_internal_and_exact(gateway_url: str) -> None:
    with pytest.raises(BifrostUserBindingUnavailable):
        BifrostUserGateway(env={"BOLTRIG_MODEL_GATEWAY_URL": gateway_url})


@pytest.mark.security
@pytest.mark.invariant("SEC-AIKEY-01")
def test_openai_compatible_route_keeps_virtual_key_as_exact_scope() -> None:
    transport = BifrostUserTransport(
        env={
            "BOLTRIG_MODEL_GATEWAY_URL": "http://bifrost:8080/v1",
            "BOLTRIG_MODEL_GATEWAY_KEY": "gateway-inference-key",
        }
    )

    endpoint, api_key, headers = transport.openai_compatible_route("vk-scope")

    assert endpoint == "http://bifrost:8080/v1"
    assert api_key == "gateway-inference-key"
    assert headers == (("x-bf-vk", "vk-scope"),)


def test_openai_compatible_route_uses_virtual_bearer_when_gateway_auth_is_off() -> None:
    transport = BifrostUserTransport(env={"BOLTRIG_MODEL_GATEWAY_URL": "http://bifrost:8080/v1"})

    endpoint, api_key, headers = transport.openai_compatible_route("vk-scope")

    assert endpoint == "http://bifrost:8080/v1"
    assert api_key == "vk-scope"
    assert headers == (("x-bf-vk", "vk-scope"),)


@pytest.mark.security
def test_provider_and_exact_model_must_agree() -> None:
    gateway = BifrostUserGateway(env={"BOLTRIG_MODEL_GATEWAY_URL": "http://bifrost:8080/v1"})
    mismatched = AiKeyResolution(
        level="user",
        scope_id="alice",
        modality="text",
        credential_ref="credential",
        provider="anthropic",
        model="openai/gpt-5.4",
    )

    with pytest.raises(BifrostUserBindingUnavailable, match="do not match"):
        # Validation happens before any request or provider secret use.
        import asyncio

        asyncio.run(gateway.ensure(InMemoryStore(), "tenant-a", mismatched, "secret"))
