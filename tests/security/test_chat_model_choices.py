"""Chat model choices expose exact names without provider topology or authority."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.models import ModelEndpoint
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
        ],
        catalogue,
    )

    response = client.get("/v1/chat/model-choices", headers=_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["reason"] is None
    assert body["default_model_name"] == "provider/base-model-20260812"
    assert body["default_choice_id"] == "default-choice"
    assert body["default_available"] is True
    assert body["default_unavailable_reason"] is None
    assert [(row["id"], row["available"], row["unavailable_reason"]) for row in body["choices"]] == [
        ("choice-a", True, None),
        ("default-choice", True, None),
        ("invalid-alias", False, "model_id_unsupported"),
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
        "default_choice_id": None,
        "default_available": False,
        "default_unavailable_reason": "catalogue_unavailable",
    }
    assert catalogue.calls == 1


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
