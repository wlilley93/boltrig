"""The two mood affordances publish plain relay frames (EMO-1: routes never
import boltrig.emotion; the relay's tap is the only interpreter)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from boltrig.kernel import Kernel
from boltrig.kernel.app import create_app
from boltrig.store import InMemoryStore

T = "acme"
HDR = {"x-boltrig-tenant": T, "x-boltrig-subject": "alice", "x-boltrig-role": "engineer"}


def _client() -> tuple[TestClient, Kernel]:
    kernel = Kernel(InMemoryStore())
    return TestClient(create_app(kernel)), kernel


def test_reset_publishes_the_reset_frame():
    client, kernel = _client()
    response = client.post("/v1/familiar/emotion/reset", headers=HDR)
    assert response.status_code == 200 and response.json() == {"status": "ok"}
    assert kernel.events.snapshot(T, "emotion") == [{"type": "emotion_reset"}]


def test_adopted_publishes_the_character_and_validates_it():
    client, kernel = _client()
    ok = client.post(
        "/v1/familiar/emotion/adopted", json={"character": "bella"}, headers=HDR
    )
    assert ok.status_code == 200 and ok.json() == {"status": "ok"}
    assert kernel.events.snapshot(T, "emotion") == [
        {"type": "character_adopted", "character": "bella"}
    ]

    missing = client.post("/v1/familiar/emotion/adopted", json={}, headers=HDR)
    assert missing.json()["status"] == "error"
    long = client.post(
        "/v1/familiar/emotion/adopted", json={"character": "x" * 65}, headers=HDR
    )
    assert long.json()["status"] == "error"
    # Neither refusal published anything.
    assert len(kernel.events.snapshot(T, "emotion")) == 1
