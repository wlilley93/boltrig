"""Worker model choices are requests over server-held, non-secret policy."""

import json

import pytest
from fastapi.testclient import TestClient

from boltrig.fleet.chat import ChatService
from boltrig.config.model_profile_views import visible_model_profiles
from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.kernel.events import EventRelay
from boltrig.store import InMemoryStore


HEADERS = {
    "x-boltrig-tenant": "acme",
    "x-boltrig-subject": "alice",
    "x-boltrig-role": "engineer",
}


@pytest.mark.invariant("SEC-WRK-02")
def test_visible_model_profiles_expose_no_provider_endpoint_or_credential(monkeypatch):
    sentinel = "https://internal-model.example/v1/SECRET"
    monkeypatch.setenv(
        "BOLTRIG_MODEL_PROFILES",
        json.dumps(
            {
                "deep_work": {
                    "provider": "openai",
                    "model": "secret-model-name",
                    "base_url": sentinel,
                }
            }
        ),
    )
    profiles = visible_model_profiles()
    assert profiles == [
        {
            "id": "deep_work",
            "label": "Deep Work",
            "routing_class": "governed",
            "data_classes": ["standard"],
            "available": True,
            "unavailable_reason": None,
        }
    ]
    wire = json.dumps(profiles)
    assert sentinel not in wire
    assert "secret-model-name" not in wire
    assert '"provider"' not in wire


@pytest.mark.invariant("SEC-WRK-02")
def test_chat_threads_only_an_approved_profile_name_and_emits_non_secret_route():
    seen = {}

    async def executor(
        *,
        tenant_id,
        user_id,
        role,
        grants,
        conversation_id,
        run_id,
        message,
        relay,
        attachments=None,
        model_profile_id=None,
    ):
        seen["profile"] = model_profile_id
        relay.publish(
            run_id,
            {
                "type": "model_routing",
                "run_id": run_id,
                "selected_profile_id": "deep-work",
                "requested_profile_id": model_profile_id,
                "routing_class": "codex",
                "reason": "approved profile selected",
                "overridden": False,
            },
        )
        relay.publish(run_id, {"type": "text_delta", "delta": "done"})

    store, relay = InMemoryStore(), EventRelay()
    chat = ChatService(store, relay, turn_executor=executor)
    client = TestClient(create_app(Kernel(store), chat_service=chat))

    response = client.post(
        "/v1/chat",
        json={"message": "hello", "model_profile_id": "deep-work", "origin": "worker"},
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert seen == {"profile": "deep-work"}
    assert '"selected_profile_id": "deep-work"' in response.text
    assert "base_url" not in response.text
    assert "credential" not in response.text


@pytest.mark.invariant("SEC-WRK-02")
def test_model_profile_endpoint_requires_principal_and_returns_safe_projection(monkeypatch):
    monkeypatch.setenv(
        "BOLTRIG_MODEL_PROFILES",
        json.dumps({"fast": {"provider": "openai", "model": "hidden"}}),
    )
    client = TestClient(create_app(Kernel(InMemoryStore())))
    response = client.get("/v1/model-profiles", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["profiles"][0]["id"] == "fast"
    assert "hidden" not in response.text
