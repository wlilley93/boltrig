"""Chat model choices expose exact names without provider topology or authority."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.identity import AiKeyResolution
from boltrig.identity.bifrost_user_binding import (
    BifrostUserGateway,
    binding_credential_ref,
)
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import AiConfig, ModelEndpoint, Organisation
from boltrig.store import InMemoryStore

_HEADERS = {
    "x-boltrig-tenant": "acme",
    "x-boltrig-subject": "alice",
    "x-boltrig-role": "member",
}


class _Catalogue:
    def __init__(self, result: dict) -> None:
        self.result = result
        self.calls = 0

    async def list_models(self) -> dict:
        self.calls += 1
        return self.result


def _endpoint(endpoint_id: str, model: str, **changes: object) -> ModelEndpoint:
    values = {
        "id": endpoint_id,
        "tenant_id": "acme",
        "kind": "bifrost",
        "model": model,
        "base_url": "http://provider-topology.internal/v1",
        "data_class": "standard",
        "modalities": ("text",),
        "is_active": True,
    }
    values.update(changes)
    return ModelEndpoint(**values)  # type: ignore[arg-type]


def _client(endpoints: list[ModelEndpoint], catalogue: _Catalogue) -> TestClient:
    store = InMemoryStore()

    async def seed() -> None:
        for endpoint in endpoints:
            await store.upsert_model_endpoint(endpoint)

    asyncio.run(seed())
    return TestClient(
        create_app(
            Kernel(store),
            platform={
                "bifrost_models": catalogue,
                "codex_trusted_provider_configured": True,
                "codex_model_id": "provider/base-model-20260812",
                "model_gateway_configured": True,
            },
        )
    )


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-02")
def test_chat_model_choices_are_tenant_scoped_exact_and_catalogue_verified() -> None:
    catalogue = _Catalogue(
        {
            "status": "ok",
            "reason": None,
            "models": [
                {
                    "id": "provider/base-model-20260812",
                    "name": "Display name must not replace the exact id",
                    "input_modalities": ["text", "image"],
                },
                {
                    "id": "provider/model-a",
                    "name": "Model A",
                    "input_modalities": ["text"],
                },
                {
                    "id": "provider/vision-only",
                    "name": "Vision only",
                    "input_modalities": ["image"],
                },
                {
                    "id": "ollama/bare-row",
                    "name": "Provider-derived, no architecture block",
                },
                {
                    "id": "provider/mis-described",
                    "name": "Carries the key malformed",
                    "input_modalities": "nope",
                },
            ],
        }
    )
    client = _client(
        [
            _endpoint("default-choice", "provider/base-model-20260812"),
            _endpoint("choice-a", "provider/model-a", kind="openai"),
            _endpoint("not-advertised", "provider/model-missing"),
            _endpoint("invalid-alias", "provider/latest"),
            _endpoint("unsafe id", "provider/model-a"),
            _endpoint("vision-upstream", "provider/vision-only"),
            _endpoint("retired", "provider/model-a", is_active=False),
            _endpoint("sensitive", "provider/model-a", data_class="sensitive"),
            _endpoint(
                "vision-row",
                "provider/vision-only",
                modalities=("vision",),
            ),
            _endpoint(
                "foreign",
                "provider/model-a",
                tenant_id="another-tenant",
            ),
            _endpoint("bare-declared", "ollama/bare-row"),
            _endpoint("mis-described", "provider/mis-described"),
        ],
        catalogue,
    )

    response = client.get("/v1/chat/model-choices", headers=_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["reason"] is None
    assert body["default_model_name"] == "provider/base-model-20260812"
    assert body["default_source"] == "platform"
    assert body["default_choice_id"] == "default-choice"
    assert body["default_available"] is True
    assert body["default_unavailable_reason"] is None
    assert [(row["id"], row["available"], row["unavailable_reason"]) for row in body["choices"]] == [
        ("bare-declared", True, None),
        ("choice-a", True, None),
        ("default-choice", True, None),
        ("invalid-alias", False, "model_id_unsupported"),
        ("mis-described", False, "text_capability_not_advertised"),
        ("not-advertised", False, "model_not_advertised"),
        ("vision-upstream", False, "text_not_supported"),
    ]
    assert next(
        row for row in body["choices"] if row["id"] == "default-choice"
    )["model_name"] == "provider/base-model-20260812"
    assert catalogue.calls == 1
    public = response.text
    assert "Display name must not replace" not in public
    assert "provider-topology" not in public
    assert "another-tenant" not in public
    assert '"base_url"' not in public
    assert '"kind"' not in public


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-02")
def test_catalogue_failure_marks_every_safe_choice_unavailable() -> None:
    catalogue = _Catalogue(
        {"status": "unavailable", "models": [], "reason": "gateway_timeout"}
    )
    client = _client(
        [_endpoint("choice-a", "provider/model-a")],
        catalogue,
    )

    response = client.get("/v1/chat/model-choices", headers=_HEADERS)

    assert response.status_code == 200
    assert response.json() == {
        "status": "unavailable",
        "reason": "gateway_timeout",
        "choices": [
            {
                "id": "choice-a",
                "model_name": "provider/model-a",
                "available": False,
                "is_default": False,
                "modalities": ["text"],
                "unavailable_reason": "catalogue_unavailable",
            }
        ],
        "default_model_name": "provider/base-model-20260812",
        "default_source": "platform",
        "default_choice_id": None,
        "default_available": False,
        "default_unavailable_reason": "catalogue_unavailable",
    }
    assert catalogue.calls == 1


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-02")
@pytest.mark.invariant("FR-AIKEY-03")
def test_personal_model_is_the_exact_available_default_after_refresh(monkeypatch) -> None:
    store = InMemoryStore()
    resolution = AiKeyResolution(
        level="user",
        scope_id="alice",
        modality="text",
        credential_ref="approved-key",
        provider="openai",
        model="openai/gpt-5.4",
    )

    async def seed() -> None:
        await store.create_org(Organisation(
            id="acme",
            name="Acme",
            slug="acme",
            allow_own_ai_keys=True,
        ))
        await store.set_credential_ref("acme", "approved-key", {"secret": "provider-secret"})
        await store.set_ai_config(AiConfig(
            tenant_id="acme",
            level="user",
            scope_id="alice",
            provider="openai",
            model="openai/gpt-5.4",
            credential_ref="approved-key",
        ))
        await store.set_credential_ref(
            "acme",
            binding_credential_ref("acme", resolution),
            {
                "secret": "vk-scoped-secret",
                "provider": "openai",
                "model_id": "openai/gpt-5.4",
                "source_credential_ref": "approved-key",
                "provider_key_id": "provider-key",
                "virtual_key_id": "virtual-key",
            },
        )

    async def usable(self, binding) -> bool:
        return binding.model_id == "openai/gpt-5.4"

    asyncio.run(seed())
    monkeypatch.setenv("BOLTRIG_MODEL_GATEWAY_URL", "http://bifrost:8080/v1")
    monkeypatch.setattr(BifrostUserGateway, "is_usable", usable)
    personal_catalogue = _Catalogue({
        "status": "unavailable",
        "models": [],
        "reason": "gateway_timeout",
    })
    client = TestClient(create_app(
        Kernel(store),
        platform={
            "bifrost_models": personal_catalogue,
            "codex_trusted_provider_configured": True,
            "codex_model_id": "provider/platform-default",
            "model_gateway_configured": True,
        },
    ))

    response = client.get("/v1/chat/model-choices", headers=_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "ok",
        "reason": None,
        "choices": [],
        "default_model_name": "openai/gpt-5.4",
        "default_source": "personal",
        "default_choice_id": None,
        "default_available": True,
        "default_unavailable_reason": None,
    }
    assert "provider-secret" not in response.text
    assert "vk-scoped-secret" not in response.text
    assert personal_catalogue.calls == 1


@pytest.mark.security
@pytest.mark.invariant("SEC-WRK-02")
def test_chat_rejects_blank_whitespace_and_oversized_choice_ids() -> None:
    client = _client(
        [],
        _Catalogue({"status": "ok", "models": [], "reason": None}),
    )
    for model_choice_id in ("", "unsafe id", "x" * 161):
        response = client.post(
            "/v1/chat",
            headers=_HEADERS,
            json={"message": "hello", "model_choice_id": model_choice_id},
        )
        assert response.status_code == 422
